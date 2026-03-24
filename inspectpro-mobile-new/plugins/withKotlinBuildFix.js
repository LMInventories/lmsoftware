/**
 * withKotlinBuildFix.js
 *
 * Expo config plugin — runs during `expo prebuild` (always executed by EAS
 * for managed-workflow builds before the Gradle build starts).
 *
 * ROOT CAUSE OF THE BUILD FAILURE
 * ────────────────────────────────
 * @react-native/gradle-plugin (RN 0.79) bundles a settings plugin whose
 * build.gradle.kts contains:
 *
 *   kotlin { jvmToolchain(17) }
 *
 * In Kotlin Gradle Plugin 2.0.21, specifying jvmToolchain ALWAYS forces the
 * Gradle Workers API for Kotlin compilation and completely overrides the
 * kotlin.compiler.execution.strategy property.  The worker spawns in a
 * separate JVM context and crashes with "Internal compiler error".
 *
 * Removing that single line makes KGP compile directly in the Gradle daemon
 * JVM.  The explicit jvmTarget.set(JvmTarget.JVM_11) in the same file is
 * untouched, so output bytecode compatibility is identical.
 *
 * DELIVERY: TWO INDEPENDENT PATHS
 * ────────────────────────────────
 * 1. withDangerousMod (this file) — runs during expo prebuild, which EAS
 *    always executes for managed-workflow projects.
 *
 * 2. scripts/eas-gradle-patch.js via package.json "postinstall" — runs on
 *    every `npm ci` / `npm install`, including the one EAS runs before
 *    prebuild.  Belt-and-suspenders: if prebuild is cached or skipped, the
 *    postinstall path still applies the patch.
 *
 * ADDITIONALLY: android/gradle.properties entries via withGradleProperties
 * ────────────────────────────────────────────────────────────────────────
 * Sets kotlin.compiler.execution.strategy=in-process and org.gradle.daemon=
 * false for the main Android project (doesn't fix the included build on its
 * own, but ensures consistent behaviour across the whole build).
 */

const { withDangerousMod, withGradleProperties } = require('@expo/config-plugins')
const fs   = require('fs')
const path = require('path')

// ── shared patch helper ───────────────────────────────────────────────────────
function patchBuildGradle(projectRoot) {
  const target = path.join(
    projectRoot,
    'node_modules', '@react-native', 'gradle-plugin',
    'settings-plugin', 'build.gradle.kts'
  )

  if (!fs.existsSync(target)) {
    console.warn('[withKotlinBuildFix] build.gradle.kts not found at:', target)
    return
  }

  const original = fs.readFileSync(target, 'utf8')

  if (!original.includes('jvmToolchain')) {
    console.log('[withKotlinBuildFix] build.gradle.kts already patched — skipping')
    return
  }

  // Remove `kotlin { jvmToolchain(N) }` — single-line block form used by RN 0.79
  const patched = original.replace(/\n[ \t]*kotlin\s*\{\s*jvmToolchain\(\d+\)\s*\}/g, '')
  fs.writeFileSync(target, patched)
  console.log('[withKotlinBuildFix] Removed jvmToolchain(17) from settings-plugin/build.gradle.kts')
}

// ── gradle.properties helpers ─────────────────────────────────────────────────
function setProp(props, key, value) {
  const existing = props.find(p => p.type === 'property' && p.key === key)
  if (existing) {
    existing.value = value
  } else {
    props.push({ type: 'property', key, value })
  }
}

function mergeJvmArgs(existing, ...toAdd) {
  let base = existing || '-Xmx4096m -XX:MaxMetaspaceSize=1g -Dfile.encoding=UTF-8'
  for (const arg of toAdd) {
    const keyMatch = arg.match(/^-D([^=]+)/)
    if (keyMatch && base.includes(`-D${keyMatch[1]}`)) {
      base = base.replace(new RegExp(`-D${keyMatch[1]}=[^\\s]*`), arg)
    } else if (!base.includes(arg)) {
      base = `${base} ${arg}`
    }
  }
  return base
}

// ── plugin export ─────────────────────────────────────────────────────────────
module.exports = function withKotlinBuildFix(config) {
  // Step 1 — patch the RN gradle plugin source during prebuild
  config = withDangerousMod(config, [
    'android',
    (config) => {
      patchBuildGradle(config.modRequest.projectRoot)
      return config
    },
  ])

  // Step 2 — write gradle.properties entries for the main Android project
  config = withGradleProperties(config, (config) => {
    const props = config.modResults

    setProp(props, 'kotlin.compiler.execution.strategy', 'in-process')
    setProp(props, 'org.gradle.daemon', 'false')

    const existing = props.find(p => p.type === 'property' && p.key === 'org.gradle.jvmargs')
    setProp(props, 'org.gradle.jvmargs', mergeJvmArgs(
      existing?.value,
      '-Dkotlin.compiler.execution.strategy=in-process',
      '-Dkotlin.daemon.enabled=false',
    ))

    return config
  })

  return config
}
