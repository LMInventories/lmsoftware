/**
 * eas-gradle-patch.js
 *
 * Purpose:
 * 1. Fix Kotlin worker crash (RN 0.79 issue)
 * 2. Force compatible AndroidX versions for Expo SDK 55
 */

const fs = require('fs')
const path = require('path')
const os = require('os')

// ─────────────────────────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────────────────────────

const ANDROIDX_VERSION = '1.15.0'

const PROPS_CONTENT = [
  'kotlin.compiler.execution.strategy=in-process',
  'org.gradle.daemon=false',
].join('\n') + '\n'

// ─────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────

function mergeProps(existing, content) {
  const newKeys = content.split('\n')
    .filter(l => l.includes('='))
    .map(l => l.split('=')[0].trim())

  const kept = (existing || '').split('\n').filter(l => {
    const key = l.split('=')[0].trim()
    return !newKeys.includes(key)
  })

  return kept.join('\n').trimEnd() + '\n' + content
}

function safeRead(file) {
  return fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : null
}

// ─────────────────────────────────────────────────────────────
// 1. FIX KOTLIN TOOLCHAIN ISSUE
// ─────────────────────────────────────────────────────────────

const settingsPluginBuild = path.join(
  __dirname,
  '..',
  'node_modules',
  '@react-native',
  'gradle-plugin',
  'settings-plugin',
  'build.gradle.kts'
)

try {
  const content = safeRead(settingsPluginBuild)

  if (!content) {
    console.warn('[patch] settings-plugin not found, skipping Kotlin fix')
  } else if (content.includes('jvmToolchain')) {
    const patched = content.replace(
      /\n\s*kotlin\s*\{\s*jvmToolchain\(\d+\)\s*\}/g,
      ''
    )

    fs.writeFileSync(settingsPluginBuild, patched)
    console.log('[patch] Removed jvmToolchain(17) ✓')
  } else {
    console.log('[patch] Kotlin already patched ✓')
  }
} catch (e) {
  console.error('[patch] Kotlin patch failed:', e.message)
}

// ─────────────────────────────────────────────────────────────
// 2. FORCE GRADLE PROPERTIES
// ─────────────────────────────────────────────────────────────

const gradleHome = path.join(os.homedir(), '.gradle')
const gradleProps = path.join(gradleHome, 'gradle.properties')

try {
  fs.mkdirSync(gradleHome, { recursive: true })

  const existing = safeRead(gradleProps)
  fs.writeFileSync(gradleProps, mergeProps(existing, PROPS_CONTENT))

  console.log('[patch] Wrote ~/.gradle/gradle.properties ✓')
} catch (e) {
  console.error('[patch] Failed writing gradle.properties:', e.message)
}

// ─────────────────────────────────────────────────────────────
// 3. PATCH RN GRADLE PLUGIN PROPS
// ─────────────────────────────────────────────────────────────

const rnPluginRoot = path.join(
  __dirname,
  '..',
  'node_modules',
  '@react-native',
  'gradle-plugin'
)

const rnPluginProps = path.join(rnPluginRoot, 'gradle.properties')

try {
  if (!fs.existsSync(rnPluginRoot)) {
    console.warn('[patch] RN gradle plugin not found')
  } else {
    const existing = safeRead(rnPluginProps)
    fs.writeFileSync(rnPluginProps, mergeProps(existing, PROPS_CONTENT))

    console.log('[patch] Patched RN gradle.properties ✓')
  }
} catch (e) {
  console.error('[patch] RN gradle patch failed:', e.message)
}

// ─────────────────────────────────────────────────────────────
// 4. FORCE ANDROIDX (CRITICAL FIX)
// ─────────────────────────────────────────────────────────────

const rootBuildGradle = path.join(__dirname, '..', 'android', 'build.gradle')

try {
  const content = safeRead(rootBuildGradle)

  if (!content) {
    console.log('[patch] android/build.gradle not found (run after prebuild)')
  } else if (!content.includes(`core-ktx:${ANDROIDX_VERSION}`)) {
    const patch = `
subprojects {
    configurations.all {
        resolutionStrategy {
            force "androidx.core:core-ktx:${ANDROIDX_VERSION}"
            force "androidx.core:core:${ANDROIDX_VERSION}"
        }
    }
}
`

    fs.writeFileSync(rootBuildGradle, content + '\n' + patch)

    console.log(`[patch] Forced AndroidX → ${ANDROIDX_VERSION} ✓`)
  } else {
    console.log('[patch] AndroidX already pinned ✓')
  }
} catch (e) {
  console.error('[patch] AndroidX patch failed:', e.message)
}

// ─────────────────────────────────────────────────────────────
// DONE
// ─────────────────────────────────────────────────────────────

console.log('\n[patch] Done\n')