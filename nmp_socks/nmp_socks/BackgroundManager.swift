import AVFoundation
import Foundation

class BackgroundManager {
    static let shared = BackgroundManager()
    private var audioPlayer: AVAudioPlayer?
    private static let silentWavData: Data = BackgroundManager.createSilentWav()

    private init() {
        setupAudioSession()
    }

    private func setupAudioSession() {
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default, options: [.mixWithOthers])
            try AVAudioSession.sharedInstance().setActive(true)
        } catch {
            NSLog("Failed to set audio session category: \(error)")
        }
    }

    func startKeepAlive() {
        if audioPlayer?.isPlaying == true {
            return
        }

        do {
            audioPlayer = try AVAudioPlayer(data: Self.silentWavData)
            audioPlayer?.numberOfLoops = -1 // Loop indefinitely
            audioPlayer?.volume = 0.01 // Very low volume
            audioPlayer?.play()
            NSLog("Background keep-alive started")
        } catch {
            NSLog("Failed to start background audio: \(error)")
        }
    }

    func stopKeepAlive() {
        audioPlayer?.stop()
        audioPlayer = nil
        NSLog("Background keep-alive stopped")
    }

    private static func createSilentWav() -> Data {
        // Simple WAV header for a silent PCM
        let sampleRate = 44100
        let channels = 1
        let bitDepth = 16
        let duration = 1
        let byteRate = sampleRate * channels * bitDepth / 8
        let blockAlign = channels * bitDepth / 8
        let dataSize = duration * byteRate
        let fileSize = 44 + dataSize

        var header = Data()
        header.append("RIFF".data(using: .ascii)!)
        header.append(UInt32(fileSize - 8).littleEndianData)
        header.append("WAVE".data(using: .ascii)!)
        header.append("fmt ".data(using: .ascii)!)
        header.append(UInt32(16).littleEndianData) // Subchunk1Size
        header.append(UInt16(1).littleEndianData) // AudioFormat (PCM)
        header.append(UInt16(channels).littleEndianData)
        header.append(UInt32(sampleRate).littleEndianData)
        header.append(UInt32(byteRate).littleEndianData)
        header.append(UInt16(blockAlign).littleEndianData)
        header.append(UInt16(bitDepth).littleEndianData)
        header.append("data".data(using: .ascii)!)
        header.append(UInt32(dataSize).littleEndianData)

        let silentData = Data(count: dataSize)
        return header + silentData
    }
}

extension UInt32 {
    var littleEndianData: Data {
        var value = littleEndian
        return Data(bytes: &value, count: MemoryLayout<UInt32>.size)
    }
}

extension UInt16 {
    var littleEndianData: Data {
        var value = littleEndian
        return Data(bytes: &value, count: MemoryLayout<UInt16>.size)
    }
}
