import Combine
import Foundation
import Network

class NmpSocksManager: ObservableObject {
    static let shared = NmpSocksManager()

    @Published var isRunning = false
    @Published var statusText = "Ready"
    @Published var localPort: UInt16 = 1080
    @Published var poolSize: Int = 8
    @Published var errorMessage: String?

    private var socksServer: SOCKS5Server?
    private var wsPool: NmpWebSocketPool?
    private let metrics = NmpMetrics.shared

    private final class RelayToken {
        private let metrics: NmpMetrics
        private var ended = false

        init(metrics: NmpMetrics) {
            self.metrics = metrics
            metrics.relayStarted()
        }

        func end() {
            guard !ended else { return }
            ended = true
            metrics.relayEnded()
        }
    }

    private final class WsRef {
        var connection: NWConnection?
    }

    private init() {}

    func toggle(endpoint: String, token: String) {
        if isRunning {
            stop()
        } else {
            start(endpoint: endpoint, token: token)
        }
    }

    private func start(endpoint: String, token: String) {
        statusText = "Starting..."

        // 1. Initialize WebSocket Pool
        wsPool = NmpWebSocketPool(endpoint: endpoint, token: token, poolSize: poolSize)

        // 2. Initialize SOCKS5 Server
        socksServer = SOCKS5Server()
        socksServer?.onConnect = { [weak self] host, port, connection in
            self?.handleSOCKSConnect(host: host, port: port, connection: connection)
        }

        do {
            try socksServer?.start(port: localPort)
            BackgroundManager.shared.startKeepAlive()
            isRunning = true
            statusText = "Listening on 127.0.0.1:\(localPort)"
            NSLog("SOCKS5 Manager: Started successfully on port \(localPort)")
        } catch {
            let errorDesc = error.localizedDescription
            statusText = "Error: \(errorDesc)"
            errorMessage = errorDesc
            stop()
        }
    }

    private func stop() {
        socksServer?.stop()
        socksServer = nil
        wsPool = nil
        BackgroundManager.shared.stopKeepAlive()
        isRunning = false
        statusText = "Stopped"
    }

    private func handleSOCKSConnect(host: String, port: UInt16, connection: SOCKS5Connection) {
        let relayToken = RelayToken(metrics: metrics)

        let wsRef = WsRef()
        connection.addOnCloseHandler { [weak self] in
            relayToken.end()
            if let ws = wsRef.connection {
                self?.wsPool?.releaseConnection(ws)
            }
        }

        // 1. Reply to client immediately (Python Client behavior)
        connection.sendSuccessResponse()

        // 2. Try to read the first payload (Fastpath)
        connection.receiveOnce(maximumLength: NmpProtocol.maxFastpathBytes) { [weak self] payload in
            let initialData = payload ?? Data()

            // 3. Prefer using the pre-connection pool
            self?.wsPool?.getPoolConnection(host: host, port: port, payload: initialData) { [weak self] wsConnection, isFastpath in
                guard let self = self, let wsConnection = wsConnection, wsConnection.state == .ready else {
                    connection.stop()
                    relayToken.end()
                    if let ws = wsConnection {
                        self?.wsPool?.releaseConnection(ws)
                    }
                    return
                }

                wsRef.connection = wsConnection

                if isFastpath {
                    // Header Fastpath mode: Host/Port/Payload already sent in Handshake
                    // Server does not send NMP_CONNECT_OK, start relay immediately
                    self.setupRelay(wsConnection: wsConnection, socksConnection: connection, relayToken: relayToken)
                } else {
                    // Binary Fastpath mode (rtype 5): Send binary packet on pooled connection
                    let connectPacket = NmpProtocol.createTcpWithDataPacket(host: host, port: port, payload: initialData)
                    let metadata = NWProtocolWebSocket.Metadata(opcode: .binary)
                    let context = NWConnection.ContentContext(identifier: "connect", metadata: [metadata])

                    wsConnection.send(content: connectPacket, contentContext: context, isComplete: true, completion: .contentProcessed { [weak self] error in
                        if let error = error {
                            NSLog("Failed to send binary connect packet: \(error)")
                            connection.stop()
                            relayToken.end()
                            self?.wsPool?.releaseConnection(wsConnection)
                            return
                        }
                        // Server does not send OK for rtype 5, start relay immediately
                        self?.setupRelay(wsConnection: wsConnection, socksConnection: connection, relayToken: relayToken)
                    })
                }
            }
        }
    }

    private func setupRelay(wsConnection: NWConnection, socksConnection: SOCKS5Connection, relayToken: RelayToken) {
        // From SOCKS5 Client to WebSocket
        socksConnection.receiveForwarding { [weak self, weak wsConnection] data in
            guard let wsConnection = wsConnection else { return }
            let metadata = NWProtocolWebSocket.Metadata(opcode: .binary)
            let context = NWConnection.ContentContext(identifier: "relay", metadata: [metadata])
            wsConnection.send(content: data, contentContext: context, isComplete: true, completion: .contentProcessed { [weak self] error in
                if let error = error {
                    NSLog("WS Send failed: \(error)")
                    socksConnection.stop()
                    if let self = self {
                        self.wsPool?.releaseConnection(wsConnection)
                        relayToken.end()
                    }
                }
            })
        }

        // From WebSocket to SOCKS5 Client
        receiveFromWS(wsConnection, connection: socksConnection, relayToken: relayToken)
    }

    private func receiveFromWS(_ wsConnection: NWConnection, connection: SOCKS5Connection, relayToken: RelayToken) {
        wsConnection.receiveMessage { [weak self, weak wsConnection] data, _, _, error in
            guard let self = self, let wsConnection = wsConnection else { return }

            if let data = data {
                connection.sendData(data)
                self.receiveFromWS(wsConnection, connection: connection, relayToken: relayToken)
            } else {
                if let error = error {
                    NSLog("WS Receive failed: \(error)")
                }
                // Connection closed or failed, clean up both sides gracefully
                connection.stop()
                self.wsPool?.releaseConnection(wsConnection)
                relayToken.end()
            }
        }
    }
}
