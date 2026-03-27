import React, { useEffect, useState } from 'react'
import { NavigationContainer } from '@react-navigation/native'
import { createStackNavigator } from '@react-navigation/stack'
import { StatusBar } from 'react-native'
import { GestureHandlerRootView } from 'react-native-gesture-handler'
import { SafeAreaProvider } from 'react-native-safe-area-context'

import { useAuthStore } from './src/stores/authStore'
import { initDatabase } from './src/services/database'

import LoginScreen from './src/screens/LoginScreen'
import InspectionListScreen from './src/screens/InspectionListScreen'
import FetchInspectionsScreen from './src/screens/FetchInspectionsScreen'
import PropertyOverviewScreen from './src/screens/PropertyOverviewScreen'
import RoomSelectionScreen from './src/screens/RoomSelectionScreen'
import RoomInspectionScreen from './src/screens/RoomInspectionScreen'
import ItemGalleryScreen from './src/screens/ItemGalleryScreen'
import SyncScreen from './src/screens/SyncScreen'
import CameraScreen from './src/screens/CameraScreen'

export type RootStackParamList = {
  Login: undefined
  InspectionList: undefined
  FetchInspections: undefined
  PropertyOverview: { inspectionId: number }
  RoomSelection: { inspectionId: number }
  RoomInspection: {
    inspectionId: number
    sectionKey: string
    sectionName: string
    sectionType: 'room' | 'fixed'
    templateSectionId?: number
    fixedSectionData?: string  // JSON stringified fixed section for 'fixed' type
    sectionIndex?: number      // 1-based position of this section in the template (for photo labels)
  }
  ItemGallery: {
    inspectionId: number
    sectionKey:   string   // current room's key
    sectionName:  string   // current room's display name
    itemKey:      string
    itemName:     string
    itemPosition?: string  // e.g. "2.4" — section.item for display label
  }
  Camera: {
    inspectionId: number
    // Gallery context — passed so the thumbnail can link straight to ItemGallery
    sectionKey?:  string
    sectionName?: string
    itemKey?:     string
    itemName?:    string
  }
  Sync: undefined
}

const Stack = createStackNavigator<RootStackParamList>()

export default function App() {
  const { isAuthenticated, initAuth } = useAuthStore()
  const [dbReady, setDbReady] = useState(false)

  useEffect(() => {
    async function bootstrap() {
      initDatabase()
      await initAuth()
      setDbReady(true)
    }
    bootstrap()
  }, [])

  if (!dbReady) return null

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <StatusBar barStyle="dark-content" backgroundColor="#f8fafc" />
        <NavigationContainer>
          <Stack.Navigator screenOptions={{ headerShown: false, cardStyle: { backgroundColor: '#f8fafc' } }}>
            {!isAuthenticated ? (
              <Stack.Screen name="Login" component={LoginScreen} />
            ) : (
              <>
                <Stack.Screen name="InspectionList"    component={InspectionListScreen} />
                <Stack.Screen name="FetchInspections"  component={FetchInspectionsScreen} />
                <Stack.Screen name="PropertyOverview"  component={PropertyOverviewScreen} />
                <Stack.Screen name="RoomSelection"     component={RoomSelectionScreen} />
                <Stack.Screen name="RoomInspection"    component={RoomInspectionScreen} />
                <Stack.Screen name="ItemGallery"       component={ItemGalleryScreen} />
                <Stack.Screen name="Camera"            component={CameraScreen} options={{ presentation: 'fullScreenModal', animation: 'slide_from_bottom' }} />
                <Stack.Screen name="Sync"              component={SyncScreen} />
              </>
            )}
          </Stack.Navigator>
        </NavigationContainer>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  )
}
