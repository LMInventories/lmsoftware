/**
 * eas-gradle-patch.js
 *
 * Runs via the `eas-build-post-install` hook AFTER npm install but BEFORE
 * expo prebuild and the Gradle build. Writes Kotlin compiler settings into
 * two locations that are guaranteed to reach the @react-native/gradle-plugin
 * included build:
 *
 *   1. ~/.gradle/gradle.properties  (Gradle user-home — applies to ALL
 *      Gradle projects and included builds on the EAS worker)
 *
 *   2. node_modules/@react-native/gradle-plugin/gradle.properties
 *      (the root of the failing included build itself)
 *
 * WHY these two locations?
 *
 *   The build fails at :gradle-plugin:settings-plugin:compileKotlin, which
 *   is inside the @react-native/gradle-plugin included build (composite build).
 *   Settings written to android/gradle.properties or via GRADLE_OPTS only
 *   affect the main Android project — they do NOT propagate as project
 *   properties to composite builds.
 *
 *   Gradle user-home properties (~/.gradle/gradle.properties) ARE inherited
 *   by ALL projects including included builds.  The included build's own
 *   gradle.properties is also authoritative for that build.
 *
 * WHAT is being set?
 *
 *   kotlin.compiler.execution.strategy=in-process
 *     Forces the Kotlin Gradle Plugin to compile in the Gradle daemon JVM
 *     (IsolationMode.NONE in the Worker API) instead of spawning a worker
 *     subprocess.  The Internal compiler error in KGP 2.0.21 occurs because
 *     settings-plugin/build.gradle.kts uses `kotlin { jvmToolchain(17) }`,
 *     which in KGP 2.0 always triggers Gradle Workers.  Setting in-process
 *     overrides that behaviour.
 *
 *   org.gradle.daemon=false
 *     Disables the Gradle daemon — each EAS build is a fresh environment so
 *     there is no warm-up benefit, and disabling the daemon removes any risk
 *     of stale daemon state from a previous failed compilation.
 */

const fs   = require('fs')
const path = require('path')
const os   = require('os')

const PROPS = [
  'kotlin.compiler.execution.strategy=in-process',
  'org.gradle.daemon=false',
].join('\n') + '\n'

// ── 1. Gradle user home ───────────────────────────────────────────────────────
const gradleHome = path.join(os.homedir(), '.gradle')
const gradleProps = path.join(gradleHome, 'gradle.properties')

try {
  fs.mkdirSync(gradleHome, { recursive: true })

  let existing = ''
  if (fs.existsSync(gradleProps)) {
    existing = fs.readFileSync(gradleProps, 'utf8')
  }

  // Merge: replace existing strategy/daemon lines, then append any new ones
  const lines = existing.split('\n').filter(l =>
    !l.startsWith('kotlin.compiler.execution.strategy') &&
    !l.startsWith('org.gradle.daemon')
  )
  const merged = lines.join('\n').trimEnd() + '\n' + PROPS

  fs.writeFileSync(gradleProps, merged)
  console.log('[eas-gradle-patch] Wrote', gradleProps)
  console.log('[eas-gradle-patch] Contents:\n' + merged)
} catch (e) {
  console.error('[eas-gradle-patch] Failed to write ~/.gradle/gradle.properties:', e.message)
  // Non-fatal — continue to the second location
}

// ── 2. @react-native/gradle-plugin root gradle.properties ────────────────────
const rnPluginRoot = path.join(
  __dirname, '..', 'node_modules', '@react-native', 'gradle-plugin'
)
const rnPluginProps = path.join(rnPluginRoot, 'gradle.properties')

try {
  if (!fs.existsSync(rnPluginRoot)) {
    console.warn('[eas-gradle-patch] @react-native/gradle-plugin not found at', rnPluginRoot)
  } else {
    let existing = ''
    if (fs.existsSync(rnPluginProps)) {
      existing = fs.readFileSync(rnPluginProps, 'utf8')
    }

    const lines = existing.split('\n').filter(l =>
      !l.startsWith('kotlin.compiler.execution.strategy') &&
      !l.startsWith('org.gradle.daemon')
    )
    const merged = lines.join('\n').trimEnd() + '\n' + PROPS

    fs.writeFileSync(rnPluginProps, merged)
    console.log('[eas-gradle-patch] Wrote', rnPluginProps)
    console.log('[eas-gradle-patch] Contents:\n' + merged)
  }
} catch (e) {
  console.error('[eas-gradle-patch] Failed to write RN plugin gradle.properties:', e.message)
}
