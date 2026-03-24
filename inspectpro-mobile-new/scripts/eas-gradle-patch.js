/**
 * eas-gradle-patch.js
 *
 * Runs via the `eas-build-post-install` hook AFTER npm install but BEFORE
 * expo prebuild and the Gradle build.
 *
 * ROOT CAUSE
 * ----------
 * @react-native/gradle-plugin (RN 0.79) / settings-plugin/build.gradle.kts
 * contains:
 *
 *   kotlin { jvmToolchain(17) }
 *
 * In Kotlin Gradle Plugin 2.0, configuring jvmToolchain ALWAYS forces the
 * Gradle Workers API for compilation, completely overriding
 * kotlin.compiler.execution.strategy.  The worker then crashes with
 * "Internal compiler error" on EAS workers.
 *
 * FIX (Step 1 — the real fix)
 * -----------------------------------------------
 * Remove the jvmToolchain(17) line from settings-plugin/build.gradle.kts.
 * This is safe because:
 *   - The tasks.withType<KotlinCompile> block already explicitly sets
 *     jvmTarget.set(JvmTarget.JVM_11), so output bytecode is unchanged.
 *   - Kotlin falls back to the Gradle daemon JVM (JDK 17 on the EAS worker),
 *     which matches the original intent.
 *   - Without jvmToolchain, KGP compiles in-process inside the daemon JVM —
 *     no worker subprocess, no crash.
 *
 * FIX (Step 2 — belt-and-suspenders)
 * ------------------------------------
 * Write kotlin.compiler.execution.strategy=in-process to:
 *   - ~/.gradle/gradle.properties  (user-home, applies to all Gradle projects
 *     including composite/included builds)
 *   - node_modules/@react-native/gradle-plugin/gradle.properties
 *     (the included build's own root, most authoritative for that build)
 */

const fs   = require('fs')
const path = require('path')
const os   = require('os')

const PROPS_CONTENT = [
  'kotlin.compiler.execution.strategy=in-process',
  'org.gradle.daemon=false',
].join('\n') + '\n'

// ── helpers ───────────────────────────────────────────────────────────────────
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

// ── 1. DIRECT PATCH: remove jvmToolchain(17) from build.gradle.kts ───────────
const settingsPluginBuild = path.join(
  __dirname, '..', 'node_modules', '@react-native', 'gradle-plugin',
  'settings-plugin', 'build.gradle.kts'
)

try {
  if (!fs.existsSync(settingsPluginBuild)) {
    console.warn('[eas-gradle-patch] build.gradle.kts not found at', settingsPluginBuild)
  } else {
    let content = fs.readFileSync(settingsPluginBuild, 'utf8')

    if (content.includes('jvmToolchain')) {
      // Remove the entire `kotlin { jvmToolchain(N) }` block (single-line form)
      const patched = content.replace(/\n\s*kotlin\s*\{\s*jvmToolchain\(\d+\)\s*\}/g, '')
      fs.writeFileSync(settingsPluginBuild, patched)
      console.log('[eas-gradle-patch] Patched settings-plugin/build.gradle.kts — removed jvmToolchain(17)')
      console.log('[eas-gradle-patch] Removed line was: kotlin { jvmToolchain(17) }')
    } else {
      console.log('[eas-gradle-patch] build.gradle.kts already patched or jvmToolchain not found — skipping')
    }
  }
} catch (e) {
  console.error('[eas-gradle-patch] Failed to patch build.gradle.kts:', e.message)
}

// ── 2. Gradle user home gradle.properties ────────────────────────────────────
const gradleHome  = path.join(os.homedir(), '.gradle')
const gradleProps = path.join(gradleHome, 'gradle.properties')

try {
  fs.mkdirSync(gradleHome, { recursive: true })
  const existing = fs.existsSync(gradleProps) ? fs.readFileSync(gradleProps, 'utf8') : ''
  fs.writeFileSync(gradleProps, mergeProps(existing, PROPS_CONTENT))
  console.log('[eas-gradle-patch] Wrote', gradleProps)
} catch (e) {
  console.error('[eas-gradle-patch] Failed to write ~/.gradle/gradle.properties:', e.message)
}

// ── 3. @react-native/gradle-plugin root gradle.properties ────────────────────
const rnPluginRoot  = path.join(__dirname, '..', 'node_modules', '@react-native', 'gradle-plugin')
const rnPluginProps = path.join(rnPluginRoot, 'gradle.properties')

try {
  if (!fs.existsSync(rnPluginRoot)) {
    console.warn('[eas-gradle-patch] @react-native/gradle-plugin not found at', rnPluginRoot)
  } else {
    const existing = fs.existsSync(rnPluginProps) ? fs.readFileSync(rnPluginProps, 'utf8') : ''
    fs.writeFileSync(rnPluginProps, mergeProps(existing, PROPS_CONTENT))
    console.log('[eas-gradle-patch] Wrote', rnPluginProps)
  }
} catch (e) {
  console.error('[eas-gradle-patch] Failed to write RN plugin gradle.properties:', e.message)
}

// ── 4. Upgrade AGP 8.8.2 → 8.9.1 in android/build.gradle ────────────────────
// androidx.core:core:1.17.0 (pulled in by Expo SDK 55 packages) requires AGP ≥ 8.9.1.
// This only does anything when android/build.gradle exists (i.e. after expo prebuild).
const androidBuildGradle = path.join(__dirname, '..', 'android', 'build.gradle')

try {
  if (!fs.existsSync(androidBuildGradle)) {
    console.log('[eas-gradle-patch] android/build.gradle not found — AGP patch skipped (run after expo prebuild)')
  } else {
    const content = fs.readFileSync(androidBuildGradle, 'utf8')
    if (content.includes('com.android.tools.build:gradle:8.8.2')) {
      const patched = content.replace(
        /com\.android\.tools\.build:gradle:8\.8\.2/g,
        'com.android.tools.build:gradle:8.9.1'
      )
      fs.writeFileSync(androidBuildGradle, patched)
      console.log('[eas-gradle-patch] Upgraded AGP: 8.8.2 → 8.9.1 in android/build.gradle ✓')
    } else {
      console.log('[eas-gradle-patch] android/build.gradle AGP already ≥ 8.9.1 — skipping')
    }
  }
} catch (e) {
  console.error('[eas-gradle-patch] Failed to patch android/build.gradle:', e.message)
}

// ── Verification ──────────────────────────────────────────────────────────────
console.log('\n[eas-gradle-patch] Verification:')

try {
  const patched = fs.readFileSync(settingsPluginBuild, 'utf8')
  const hasToolchain = patched.includes('jvmToolchain')
  console.log('  build.gradle.kts jvmToolchain present:', hasToolchain, hasToolchain ? '⚠️  NOT REMOVED' : '✓ removed')
} catch (e) {
  console.log('  build.gradle.kts: could not verify')
}

try {
  const gp = fs.readFileSync(gradleProps, 'utf8')
  console.log('  ~/.gradle/gradle.properties:\n' + gp.split('\n').map(l => '    ' + l).join('\n'))
} catch (e) {
  console.log('  ~/.gradle/gradle.properties: not found')
}
