import { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.inspectpro.mobile',
  appName: 'InspectPro',
  webDir: 'dist',
  server: {
    // During development, point the WebView at your local Vite dev server.
    // Comment this out for production builds — the built dist/ will be used instead.
    // url: 'http://192.168.1.X:5173',  // ← replace with your machine's LAN IP
    cleartext: true,
  },
  android: {
    buildOptions: {
      keystorePath: undefined,
      keystoreAlias: undefined,
    },
  },
  plugins: {
    CapacitorSQLite: {
      iosDatabaseLocation: 'Library/CapacitorDatabase',
      iosIsEncryption: false,
      androidIsEncryption: false,
      electronIsEncryption: false,
    },
    // Microphone permission label shown to users
    Microphone: {
      microphoneUsageDescription: 'Used to record dictation for inspection items.',
    },
  },
}

export default config
