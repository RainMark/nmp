import Foundation
import Network

class SOCKS5Server {
    private var listener: NWListener?
    private let queue = DispatchQueue(label: "com.nmp.socks.server")
    private var connections: [UUID: SOCKS5Connection] = [:]

    var onConnect: ((String, UInt16, SOCKS5Connection) -> Void)?

    func start(port: UInt16) throws {
        let tcpOptions = NWProtocolTCP.Options()
        tcpOptions.enableKeepalive = true
        tcpOptions.keepaliveIdle = 30

        let parameters = NWParameters(tls: nil, tcp: tcpOptions)
        // Allow port reuse to avoid restart failures
        parameters.allowLocalEndpointReuse = true

        listener = try NWListener(using: parameters, on: NWEndpoint.Port(rawValue: port)!)

        listener?.stateUpdateHandler = { state in
            switch state {
            case .ready:
                NSLog("SOCKS5 Server ready on port \(port)")
            case let .failed(error):
                NSLog("SOCKS5 Server failed: \(error)")
            default:
                break
            }
        }

        listener?.newConnectionHandler = { [weak self] nwConnection in
            self?.handleNewConnection(nwConnection)
        }

        listener?.start(queue: queue)
    }

    func stop() {
        listener?.cancel()
        for conn in connections.values {
            conn.stop()
        }
        connections.removeAll()
    }

    private func handleNewConnection(_ nwConnection: NWConnection) {
        let id = UUID()
        let connection = SOCKS5Connection(nwConnection: nwConnection, queue: queue)
        connections[id] = connection

        connection.addOnCloseHandler { [weak self] in
            self?.connections.removeValue(forKey: id)
        }

        connection.onSOCKSConnect = { [weak self] host, port in
            self?.onConnect?(host, port, connection)
        }

        connection.start()
    }
}

class SOCKS5Connection {
    let nwConnection: NWConnection
    let queue: DispatchQueue
    private var onCloseHandlers: [() -> Void] = []
    var onSOCKSConnect: ((String, UInt16) -> Void)?

    private var state: ConnectionState = .handshake
    private var isClosed = false

    enum ConnectionState {
        case handshake
        case request
        case forwarding
    }

    init(nwConnection: NWConnection, queue: DispatchQueue) {
        self.nwConnection = nwConnection
        self.queue = queue
    }

    func addOnCloseHandler(_ handler: @escaping () -> Void) {
        queue.async { [weak self] in
            guard let self = self else { return }
            if self.isClosed {
                handler()
                return
            }
            self.onCloseHandlers.append(handler)
        }
    }

    func start() {
        nwConnection.stateUpdateHandler = { [weak self] state in
            switch state {
            case .failed, .cancelled:
                self?.stop()
            default:
                break
            }
        }
        nwConnection.start(queue: queue)
        receiveHandshake()
    }

    func stop() {
        queue.async { [weak self] in
            guard let self = self, !self.isClosed else { return }
            self.isClosed = true
            self.nwConnection.cancel()
            let handlers = self.onCloseHandlers
            self.onCloseHandlers.removeAll()
            for h in handlers {
                h()
            }
        }
    }

    private func receiveHandshake() {
        nwConnection.receive(minimumIncompleteLength: 2, maximumLength: 257) { [weak self] data, _, _, error in
            guard let self = self, let data = data, error == nil else {
                self?.stop()
                return
            }

            // SOCKS5 Handshake: VER (1) | NMETHODS (1) | METHODS (1-255)
            guard data.count >= 2, data[0] == 0x05 else {
                self.stop()
                return
            }

            // Response: VER (0x05) | METHOD (0x00 - No Auth)
            let response = Data([0x05, 0x00])
            self.nwConnection.send(content: response, completion: .contentProcessed { error in
                if error == nil {
                    self.state = .request
                    self.receiveRequest()
                } else {
                    self.stop()
                }
            })
        }
    }

    private func receiveRequest() {
        nwConnection.receive(minimumIncompleteLength: 4, maximumLength: 512) { [weak self] data, _, _, error in
            guard let self = self, let data = data, error == nil else {
                self?.stop()
                return
            }

            // VER (1) | CMD (1) | RSV (1) | ATYP (1) | DST.ADDR | DST.PORT
            guard data.count >= 4, data[0] == 0x05, data[1] == 0x01 else {
                self.stop()
                return
            }

            var host = ""
            var portOffset = 0

            let atyp = data[3]
            switch atyp {
            case 0x01: // IPv4
                if data.count >= 10 {
                    host = "\(data[4]).\(data[5]).\(data[6]).\(data[7])"
                    portOffset = 8
                }
            case 0x03: // Domain
                let len = Int(data[4])
                if data.count >= 7 + len {
                    host = String(data: data[5 ..< (5 + len)], encoding: .utf8) ?? ""
                    portOffset = 5 + len
                }
            default:
                self.stop()
                return
            }

            guard !host.isEmpty else {
                self.stop()
                return
            }

            let port = UInt16(data[portOffset]) << 8 | UInt16(data[portOffset + 1])

            // Signal to server that we want to connect to this host:port
            self.onSOCKSConnect?(host, port)
        }
    }

    func sendSuccessResponse() {
        // VER (0x05) | REP (0x00 success) | RSV (0x00) | ATYP (0x01) | BND.ADDR (4 bytes) | BND.PORT (2 bytes)
        let response = Data([0x05, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        nwConnection.send(content: response, completion: .contentProcessed { [weak self] error in
            if error == nil {
                self?.state = .forwarding
            } else {
                self?.stop()
            }
        })
    }

    func sendData(_ data: Data) {
        nwConnection.send(content: data, completion: .contentProcessed { [weak self] error in
            if error != nil {
                self?.stop()
            }
        })
    }

    func receiveForwarding(callback: @escaping (Data) -> Void) {
        nwConnection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, isComplete, error in
            if let data = data {
                callback(data)
                self?.receiveForwarding(callback: callback)
            } else if isComplete || error != nil {
                self?.stop()
            }
        }
    }

    func receiveOnce(maximumLength: Int, callback: @escaping (Data?) -> Void) {
        nwConnection.receive(minimumIncompleteLength: 1, maximumLength: maximumLength) { data, _, _, _ in
            if let data = data {
                callback(data)
            } else {
                callback(nil)
            }
        }
    }
}
