import Foundation
import Network

class NmpWebSocketPool {
    private struct PooledConnection {
        let connection: NWConnection
        let expiryDate: Date
    }

    private let endpoint: URL
    private let token: String
    private let queue = DispatchQueue(label: "com.nmp.wspool", attributes: .concurrent)

    private let maxPoolSize: Int
    private var pool = [PooledConnection]()
    private var connectingCount = 0
    private var cleaningConnections = [NWConnection]()
    private var maintenanceTimer: DispatchSourceTimer?
    private let metrics = NmpMetrics.shared

    init(endpoint: String, token: String, poolSize: Int = 8) {
        var urlString = endpoint
        if !urlString.hasSuffix("/") { urlString += "/" }
        self.endpoint = URL(string: urlString)!
        self.token = token
        maxPoolSize = poolSize

        startMaintenanceTimer()
        maintainPool()
    }

    deinit {
        maintenanceTimer?.cancel()
        queue.async(flags: .barrier) {
            for item in self.pool {
                item.connection.cancel()
            }
            self.pool.removeAll()
            for conn in self.cleaningConnections {
                conn.cancel()
            }
            self.cleaningConnections.removeAll()
        }
    }

    /// Get a connection from the pool. Prefers ready connections, otherwise creates a new one.
    func getPoolConnection(host: String, port: UInt16, payload: Data, completion: @escaping (NWConnection?, Bool) -> Void) {
        queue.async(flags: .barrier) { [weak self] in
            guard let self = self else { return }

            self.prunePool(now: Date())

            // 2. Try to get the first available connection
            if let first = self.pool.first {
                self.pool.removeFirst()
                self.maintainPool() // Refill pool asynchronously
                self.metrics.recordPoolHit()
                self.metrics.setPoolState(idle: self.pool.count, connecting: self.connectingCount, cleaning: self.cleaningConnections.count)
                completion(first.connection, false)
            } else {
                // No ready connection, create a new one with Fastpath headers immediately (0-RTT)
                self.metrics.recordPoolMiss()
                self.metrics.setPoolState(idle: self.pool.count, connecting: self.connectingCount, cleaning: self.cleaningConnections.count)
                let headers: [String: String] = [
                    NmpProtocol.fastpathHost: host,
                    NmpProtocol.fastpathPort: String(port),
                    NmpProtocol.fastpathPayload: payload.base64EncodedString(),
                ]
                self.createNewConnection(headers: headers) { conn in
                    completion(conn, true)
                }
            }
        }
    }

    /// Public method to cancel a connection gracefully
    func releaseConnection(_ connection: NWConnection) {
        queue.async(flags: .barrier) { [weak self] in
            self?.gracefulCancel(connection, shouldCancel: true)
        }
    }

    private func startMaintenanceTimer() {
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + 5, repeating: .seconds(5))
        timer.setEventHandler { [weak self] in
            self?.maintainPool()
        }
        timer.resume()
        maintenanceTimer = timer
    }

    private func maintainPool() {
        queue.async(flags: .barrier) { [weak self] in
            guard let self = self else { return }

            self.prunePool(now: Date())

            // 2. Check if refill is needed
            let currentTotal = self.pool.count + self.connectingCount
            if currentTotal < self.maxPoolSize {
                let needed = self.maxPoolSize - currentTotal
                for _ in 0 ..< needed {
                    self.connectingCount += 1
                    self.metrics.setPoolState(idle: self.pool.count, connecting: self.connectingCount, cleaning: self.cleaningConnections.count)
                    self.createNewConnection(headers: nil) { [weak self] conn in
                        guard let self = self else { return }
                        self.queue.async(flags: .barrier) {
                            self.connectingCount -= 1
                            if let conn = conn {
                                let expiry = Date().addingTimeInterval(Double.random(in: 10 ... 30))
                                self.pool.append(PooledConnection(connection: conn, expiryDate: expiry))
                                self.metrics.recordConnectionCreated()
                            }
                            self.metrics.setPoolState(idle: self.pool.count, connecting: self.connectingCount, cleaning: self.cleaningConnections.count)
                        }
                    }
                }
            }

            self.metrics.setPoolState(idle: self.pool.count, connecting: self.connectingCount, cleaning: self.cleaningConnections.count)
        }
    }

    private func prunePool(now: Date) {
        if pool.isEmpty {
            return
        }

        var newPool = [PooledConnection]()
        newPool.reserveCapacity(pool.count)

        for item in pool {
            if item.expiryDate > now, item.connection.state == .ready {
                newPool.append(item)
            } else {
                gracefulCancel(item.connection, shouldCancel: true)
            }
        }

        pool = newPool
    }

    private var cancellingIds = Set<ObjectIdentifier>()

    private func gracefulCancel(_ connection: NWConnection, shouldCancel: Bool) {
        let id = ObjectIdentifier(connection)
        guard !cancellingIds.contains(id) else { return }
        cancellingIds.insert(id)

        if !cleaningConnections.contains(where: { $0 === connection }) {
            cleaningConnections.append(connection)
            metrics.setPoolState(idle: pool.count, connecting: connectingCount, cleaning: cleaningConnections.count)
        }

        if shouldCancel {
            connection.cancel()
            metrics.recordConnectionCancelled()
        }

        queue.asyncAfter(deadline: .now() + 15, flags: .barrier) { [weak self] in
            self?.cancellingIds.remove(id)
            self?.cleaningConnections.removeAll { $0 === connection }
            if let self = self {
                self.metrics.setPoolState(idle: self.pool.count, connecting: self.connectingCount, cleaning: self.cleaningConnections.count)
            }
        }
    }

    private func createNewConnection(headers: [String: String]?, completion: @escaping (NWConnection?) -> Void) {
        let dummy = String(UUID().uuidString.prefix(4))
        let wsUrl = endpoint.appendingPathComponent(token).appendingPathComponent(dummy)

        let isTLS = endpoint.scheme?.lowercased() == "wss" || endpoint.scheme?.lowercased() == "https"
        let parameters = isTLS ? NWParameters.tls : NWParameters.tcp

        if let tcpOptions = parameters.defaultProtocolStack.transportProtocol as? NWProtocolTCP.Options {
            tcpOptions.noDelay = true
            tcpOptions.enableKeepalive = true
        }

        let wsOptions = NWProtocolWebSocket.Options()
        wsOptions.autoReplyPing = true
        if let headers = headers {
            wsOptions.setAdditionalHeaders(headers.map { ($0.key, $0.value) })
        }

        parameters.defaultProtocolStack.applicationProtocols.insert(wsOptions, at: 0)
        parameters.prohibitedInterfaceTypes = []
        parameters.allowFastOpen = false

        let connection = NWConnection(to: .url(wsUrl), using: parameters)

        var hasReplied = false
        connection.stateUpdateHandler = { [weak self, weak connection] state in
            guard let connection = connection else { return }

            switch state {
            case .ready:
                if !hasReplied {
                    hasReplied = true
                    completion(connection)
                }
            case .failed, .cancelled:
                if !hasReplied {
                    hasReplied = true
                    completion(nil)
                }

                // Do not call cancel() here. Holding the reference avoids teardown races.
                self?.queue.async(flags: .barrier) {
                    self?.gracefulCancel(connection, shouldCancel: false)
                }
            default:
                break
            }
        }

        connection.start(queue: queue)
    }
}
