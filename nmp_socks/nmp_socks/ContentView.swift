import SwiftUI

struct ContentView: View {
    @ObservedObject var manager = NmpSocksManager.shared
    @ObservedObject var metrics = NmpMetrics.shared

    @AppStorage("nmp_endpoint") private var endpoint = ""
    @AppStorage("nmp_token") private var token = ""
    @AppStorage("nmp_local_port") private var localPort = 1234
    @AppStorage("nmp_pool_size") private var poolSize = 8

    @State private var portString: String = ""
    @State private var poolSizeString: String = ""
    @State private var showToast = false
    @State private var toastMessage = ""

    var body: some View {
        ZStack {
            // Root Background to eliminate black blocks
            Color(UIColor.systemGroupedBackground)
                .ignoresSafeArea()

            NavigationView {
                VStack(spacing: 0) {
                    VStack(spacing: 25) {
                        // --- Status Section ---
                        VStack(spacing: 15) {
                            ZStack {
                                // Outer Ring with rich color
                                Circle()
                                    .stroke(
                                        manager.isRunning ?
                                            LinearGradient(colors: [Color(red: 0, green: 0.9, blue: 0.4), Color(red: 0, green: 0.5, blue: 1.0)], startPoint: .topLeading, endPoint: .bottomTrailing) :
                                            LinearGradient(colors: [.secondary.opacity(0.3)], startPoint: .top, endPoint: .bottom),
                                        lineWidth: 4
                                    )
                                    .frame(width: 140, height: 140)

                                // Main Button Circle with vibrant colors
                                Circle()
                                    .fill(
                                        manager.isRunning ?
                                            LinearGradient(colors: [Color(red: 0, green: 0.9, blue: 0.4), Color(red: 0, green: 0.5, blue: 1.0)], startPoint: .topLeading, endPoint: .bottomTrailing) :
                                            LinearGradient(colors: [Color(white: 0.4), Color(white: 0.2)], startPoint: .topLeading, endPoint: .bottomTrailing)
                                    )
                                    .frame(width: 115, height: 115)
                                    .shadow(color: (manager.isRunning ? Color.green : Color.black).opacity(0.5), radius: 15, x: 0, y: 8)

                                Image(systemName: "power")
                                    .font(.system(size: 44, weight: .bold))
                                    .foregroundColor(.white)
                            }
                            .onTapGesture {
                                toggleServer()
                            }
                            .disabled(endpoint.isEmpty || token.isEmpty)
                            .opacity((endpoint.isEmpty || token.isEmpty) ? 0.4 : 1.0)

                            VStack(spacing: 4) {
                                Text(manager.isRunning ? "CONNECTED" : (endpoint.isEmpty || token.isEmpty ? "SETUP REQUIRED" : "DISCONNECTED"))
                                    .font(.system(size: 13, weight: .black, design: .rounded))
                                    .foregroundColor(manager.isRunning ? .green : .primary)

                                Text(manager.statusText)
                                    .font(.system(size: 12, weight: .bold, design: .rounded))
                                    .foregroundColor(.secondary)

                                Text(metrics.summaryLine)
                                    .font(.system(size: 11, weight: .semibold, design: .rounded))
                                    .foregroundColor(.secondary)
                            }
                        }
                        .padding(.top, 30)

                        // --- Configuration Section ---
                        VStack(alignment: .leading, spacing: 10) {
                            Text("NETWORK SETTINGS")
                                .font(.system(size: 11, weight: .black, design: .rounded))
                                .foregroundColor(.secondary)
                                .padding(.leading, 16)

                            VStack(spacing: 0) {
                                ConfigRow(icon: "link", title: "Endpoint", color: .blue) {
                                    TextField("wss://your-server.com", text: $endpoint)
                                        .keyboardType(.URL)
                                        .autocapitalization(.none)
                                        .disableAutocorrection(true)
                                }

                                Divider().padding(.leading, 52)

                                ConfigRow(icon: "key.fill", title: "Token", color: .purple) {
                                    TextField("Required", text: $token)
                                        .autocapitalization(.none)
                                        .disableAutocorrection(true)
                                }

                                Divider().padding(.leading, 52)

                                ConfigRow(icon: "terminal.fill", title: "Local Port", color: .orange) {
                                    TextField("1234", text: $portString)
                                        .keyboardType(.numberPad)
                                        .onChange(of: portString) { newValue in
                                            let filtered = newValue.filter { "0123456789".contains($0) }
                                            if filtered != newValue { portString = filtered }
                                            if let p = UInt16(filtered) {
                                                localPort = Int(p)
                                                manager.localPort = p
                                            }
                                        }
                                }

                                Divider().padding(.leading, 52)

                                ConfigRow(icon: "bolt.horizontal.fill", title: "Idle Pool", color: .green) {
                                    TextField("8", text: $poolSizeString)
                                        .keyboardType(.numberPad)
                                        .onChange(of: poolSizeString) { newValue in
                                            let filtered = newValue.filter { "0123456789".contains($0) }
                                            if filtered != newValue { poolSizeString = filtered }
                                            if let s = Int(filtered) {
                                                let clamped = max(0, min(s, 64))
                                                poolSize = clamped
                                                manager.poolSize = clamped
                                            }
                                        }
                                }
                            }
                            .background(Color(UIColor.secondarySystemGroupedBackground))
                            .cornerRadius(16)
                        }
                        .padding(.horizontal)

                        Spacer()
                    }
                }
                .navigationBarHidden(true)
                .background(Color(UIColor.systemGroupedBackground).ignoresSafeArea())
            }
            .navigationViewStyle(StackNavigationViewStyle())
            .onAppear {
                setupNavBarAppearance()
            }

            // --- Toast Message ---
            if showToast {
                VStack {
                    Spacer()
                    HStack(spacing: 12) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundColor(.yellow)
                        Text(toastMessage)
                            .font(.system(size: 14, weight: .bold, design: .rounded))
                            .foregroundColor(.white)
                    }
                    .padding(.vertical, 14)
                    .padding(.horizontal, 24)
                    .background(VisualEffectView(effect: UIBlurEffect(style: .dark)).cornerRadius(25))
                    .padding(.bottom, 50)
                }
                .zIndex(1)
            }
        }
        .onAppear {
            portString = String(localPort)
            poolSizeString = String(poolSize)
            manager.localPort = UInt16(localPort)
            manager.poolSize = poolSize
        }
        .onChange(of: manager.errorMessage) { newValue in
            if let msg = newValue {
                triggerToast(msg)
                manager.errorMessage = nil
            }
        }
    }

    private func triggerToast(_ message: String) {
        toastMessage = message
        showToast = true

        DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
            showToast = false
        }
    }

    private func setupNavBarAppearance() {
        let appearance = UINavigationBarAppearance()
        appearance.configureWithTransparentBackground()
        appearance.backgroundColor = .clear
        appearance.shadowColor = .clear

        // Force transparent bar for iOS 15
        UINavigationBar.appearance().standardAppearance = appearance
        UINavigationBar.appearance().compactAppearance = appearance
        UINavigationBar.appearance().scrollEdgeAppearance = appearance

        // Also fix TabBar just in case
        let tabBarAppearance = UITabBarAppearance()
        tabBarAppearance.configureWithTransparentBackground()
        tabBarAppearance.backgroundColor = .clear
        UITabBar.appearance().standardAppearance = tabBarAppearance
        if #available(iOS 15.0, *) {
            UITabBar.appearance().scrollEdgeAppearance = tabBarAppearance
        }
    }

    private func toggleServer() {
        if !endpoint.isEmpty, !token.isEmpty {
            let generator = UIImpactFeedbackGenerator(style: .medium)
            generator.impactOccurred()
            manager.toggle(endpoint: endpoint, token: token)
        }
    }
}

// --- Helper Views ---

struct ConfigRow<Content: View>: View {
    let icon: String
    let title: String
    let color: Color
    let content: () -> Content

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 12, weight: .bold))
                .foregroundColor(.white)
                .frame(width: 24, height: 24)
                .background(RoundedRectangle(cornerRadius: 6).fill(color))

            Text(title)
                .font(.system(size: 15, weight: .medium, design: .rounded))
                .foregroundColor(.primary)

            content()
                .font(.system(size: 15, design: .rounded))
                .multilineTextAlignment(.trailing)
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .padding(.vertical, 8)
        .padding(.horizontal, 16)
        .frame(minHeight: 44)
    }
}

// --- Extensions ---

struct VisualEffectView: UIViewRepresentable {
    var effect: UIVisualEffect?
    func makeUIView(context _: Context) -> UIVisualEffectView {
        UIVisualEffectView(effect: effect)
    }

    func updateUIView(_ uiView: UIVisualEffectView, context _: Context) {
        uiView.effect = effect
    }
}
