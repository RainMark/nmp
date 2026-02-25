import Foundation

final class NmpMetrics: ObservableObject {
    static let shared = NmpMetrics()

    @Published private(set) var poolHits: UInt64 = 0
    @Published private(set) var poolMisses: UInt64 = 0
    @Published private(set) var connectionsCreated: UInt64 = 0
    @Published private(set) var connectionsCancelled: UInt64 = 0

    @Published private(set) var poolIdleCount: Int = 0
    @Published private(set) var poolConnectingCount: Int = 0
    @Published private(set) var poolCleaningCount: Int = 0
    @Published private(set) var activeRelays: Int = 0

    private let lock = DispatchQueue(label: "com.nmp.metrics")

    private init() {}

    var poolHitRate: Double {
        let hits = Double(poolHits)
        let total = Double(poolHits + poolMisses)
        guard total > 0 else { return 0 }
        return hits / total
    }

    var summaryLine: String {
        let pct = Int((poolHitRate * 100).rounded())
        return "idle: \(poolIdleCount)  conn: \(poolConnectingCount)  cleaning: \(poolCleaningCount)  hit: \(pct)%  relays: \(activeRelays)"
    }

    func recordPoolHit() {
        lock.async {
            let next = self.poolHits + 1
            DispatchQueue.main.async {
                self.poolHits = next
            }
        }
    }

    func recordPoolMiss() {
        lock.async {
            let next = self.poolMisses + 1
            DispatchQueue.main.async {
                self.poolMisses = next
            }
        }
    }

    func recordConnectionCreated() {
        lock.async {
            let next = self.connectionsCreated + 1
            DispatchQueue.main.async {
                self.connectionsCreated = next
            }
        }
    }

    func recordConnectionCancelled() {
        lock.async {
            let next = self.connectionsCancelled + 1
            DispatchQueue.main.async {
                self.connectionsCancelled = next
            }
        }
    }

    func setPoolState(idle: Int, connecting: Int, cleaning: Int) {
        DispatchQueue.main.async {
            self.poolIdleCount = idle
            self.poolConnectingCount = connecting
            self.poolCleaningCount = cleaning
        }
    }

    func relayStarted() {
        DispatchQueue.main.async {
            self.activeRelays += 1
        }
    }

    func relayEnded() {
        DispatchQueue.main.async {
            self.activeRelays = max(0, self.activeRelays - 1)
        }
    }
}
