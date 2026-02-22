import { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.inspectpro.mobile',
  appName: 'InspectPro',
  webDir: 'dist',
  android: {
    allowMixedContent: true,
  },
  plugins: {
    CapacitorSQLite: {
      androidIsEncryption: false,
    },
  },
}

export default config