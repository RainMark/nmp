import Foundation

enum NmpProtocol {
    /// Command types
    enum CommandType: UInt8 {
        case tcpIP = 1
        case tcpDomain = 3
        case udpIP = 4
        case tcpWithData = 5
    }

    // Connection response codes
    static let connectOk: UInt8 = 0
    static let connectFailed: UInt8 = 1

    // Fastpath Header keys
    static let fastpathHost = "Nmp-Fastpath-Host"
    static let fastpathPort = "Nmp-Fastpath-Port"
    static let fastpathPayload = "Nmp-Fastpath-Payload"

    /// Maximum Fastpath data size (matches Python client)
    static let maxFastpathBytes = 4 * 1024

    /// Construct TCP connection packet (without payload)
    static func createTcpConnectPacket(host: String, port: UInt16) -> Data {
        var data = Data()

        // Check if host is IPv4
        var addr = in_addr()
        if inet_pton(AF_INET, host, &addr) == 1 {
            // IPv4
            data.append(CommandType.tcpIP.rawValue)
            data.append(Data(bytes: &addr, count: 4))
            var bigPort = port.bigEndian
            data.append(Data(bytes: &bigPort, count: 2))
        } else {
            // Domain
            data.append(CommandType.tcpDomain.rawValue)
            var bigPort = port.bigEndian
            data.append(Data(bytes: &bigPort, count: 2))
            if let hostData = host.data(using: .utf8) {
                data.append(hostData)
            }
        }

        return data
    }

    /// Construct TCP connection packet with payload (NMP_TCP_PIPE_WITH_DATA)
    static func createTcpWithDataPacket(host: String, port: UInt16, payload: Data) -> Data {
        var data = Data()
        data.append(CommandType.tcpWithData.rawValue)
        var bigPort = port.bigEndian
        var hostLength = UInt16(host.utf8.count).bigEndian
        data.append(Data(bytes: &bigPort, count: 2))
        data.append(Data(bytes: &hostLength, count: 2))
        if let hostData = host.data(using: .utf8) {
            data.append(hostData)
        }
        data.append(payload)
        return data
    }

    /// Construct UDP forwarding packet (NMP_UDP_PIPE_IP)
    static func createUdpPacket(hostIP: String, port: UInt16, payload: Data) -> Data? {
        var data = Data()
        // Convert IP string to 4-byte address
        var addr = in_addr()
        guard inet_pton(AF_INET, hostIP, &addr) == 1 else { return nil }

        data.append(Data(bytes: &addr, count: 4))
        var bigPort = port.bigEndian
        data.append(Data(bytes: &bigPort, count: 2))
        data.append(payload)
        return data
    }
}
