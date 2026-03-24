/**
 * withKotlinBuildFix.js
 *
 * Expo config plugin — runs during `expo prebuild`.
 *
 * ROOT CAUSE (confirmed from full build log)
 * ─────────────────────────────────────────
 * Gradle 9.0.0 bundles Kotlin 2.2.0 internally.
 * @react-native/gradle-plugin (RN 0.79.0) uses KGP 2.0.21.
 * KGP 2.0.21 cannot read Kotlin 2.2.0 binary metadata, so it crashes:
 *
 *   e: gradle-api-9.0.0.jar — binary version of its metadata is 2.2.0,
 *      expected version is 2.0.0
 *   e: Compiler terminated with internal error
 *
 * Expo SDK 55 generates an Android project with Gradle 9.0.0 in its wrapper,
 * but RN 0.79.0's own gradle-plugin ships with Gradle 8.13 — meaning 8.13 is
 * the version Meta actually tested and supports for RN 0.79.0.
 *
 * THE FIX
 * ───────
 * 1. Downgrade the Android project's Gradle wrapper from 9.0.0 → 8.13.
 *    Gradle 8.13 bundles Kotlin 2.0.x, which is compatible with KGP 2.0.21.
 *    AGP 8.8.2 (also used by RN 0.79.0) is fully supported on Gradle 8.13.
 *
 * 2. Remove `kotlin { jvmToolchain(17) }` from settings-plugin/build.gradle.kts.
 *    Belt-and-suspenders: prevents the Gradle Workers API from being forced by
 *    jvmToolchain even on Gradle 8.13.
 *
 * 3. Set gradle.properties entries for the main Android project (in-process,
 *    no daemon) as additional safety.
 */

const { withDangerousMod, withGradleProperties, withAppBuildGradle } = require('@expo/config-plugins')
const fs   = require('fs')
const path = require('path')

// ── 1. Downgrade Gradle wrapper to 8.13 ──────────────────────────────────────
function patchGradleWrapper(projectRoot) {
  const wrapperProps = path.join(
    projectRoot, 'android', 'gradle', 'wrapper', 'gradle-wrapper.properties'
  )

  if (!fs.existsSync(wrapperProps)) {
    console.warn('[withKotlinBuildFix] gradle-wrapper.properties not found at:', wrapperProps)
    return
  }

  const original = fs.readFileSync(wrapperProps, 'utf8')
  const gradleVersionMatch = original.match(/gradle-(\d+\.\d+(?:\.\d+)?)-/)
  const currentVersion = gradleVersionMatch ? gradleVersionMatch[1] : 'unknown'

  if (currentVersion === '8.13') {
    console.log('[withKotlinBuildFix] gradle-wrapper.properties already at 8.13 — skipping')
    return
  }

  const patched = original.replace(
    /distributionUrl=.*gradle-.*\.zip/,
    'distributionUrl=https\\://services.gradle.org/distributions/gradle-8.13-bin.zip'
  )
  fs.writeFileSync(wrapperProps, patched)
  console.log(`[withKotlinBuildFix] Downgraded Gradle wrapper: ${currentVersion} → 8.13`)
}

// ── 2. Remove jvmToolchain(17) from settings-plugin ──────────────────────────
function patchSettingsPlugin(projectRoot) {
  const target = path.join(
    projectRoot,
    'node_modules', '@react-native', 'gradle-plugin',
    'settings-plugin', 'build.gradle.kts'
  )

  if (!fs.existsSync(target)) {
    console.warn('[withKotlinBuildFix] settings-plugin/build.gradle.kts not found at:', target)
    return
  }

  const original = fs.readFileSync(target, 'utf8')
  if (!original.includes('jvmToolchain')) {
    console.log('[withKotlinBuildFix] jvmToolchain already removed from build.gradle.kts — skipping')
    return
  }

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

// ── 3. Remove hermesCommand from app/build.gradle ────────────────────────────
// In RN 0.79 the hermes-engine npm package no longer exists as a standalone
// package — Hermes is bundled inside com.facebook.react:hermes-android.
// The generated app/build.gradle has:
//   hermesCommand = new File(["node","--print","require.resolve('hermes-engine/...')"]
//                   .execute(null, rootDir).text.trim()).getParentFile().getAbsolutePath() + "..."
// When require.resolve fails (package not found), stdout is empty, getParentFile()
// returns null, and getAbsolutePath() on null throws NPE at build configuration time.
// For debug APKs JS is not pre-bundled so hermesCommand is never consumed anyway.
function withHermesCommandFix(config) {
  return withAppBuildGradle(config, (config) => {
    const original = config.modResults.contents
    // Comment out any hermesCommand line that uses node/require.resolve
    const patched = original.replace(
      /^(\s*hermesCommand\s*=\s*new File\(\["node"[^\n]+)\n/m,
      '    // hermesCommand omitted: hermes-engine is bundled in RN 0.79, not a standalone npm pkg\n'
    )
    if (patched !== original) {
      console.log('[withKotlinBuildFix] Commented out hermesCommand line in app/build.gradle')
    } else {
      console.log('[withKotlinBuildFix] hermesCommand line not found or already patched — skipping')
    }
    config.modResults.contents = patched
    return config
  })
}

// ── plugin export ─────────────────────────────────────────────────────────────
module.exports = function withKotlinBuildFix(config) {
  // Step 1 — patch both files during prebuild (runs after android/ is generated)
  config = withDangerousMod(config, [
    'android',
    (config) => {
      patchGradleWrapper(config.modRequest.projectRoot)
      patchSettingsPlugin(config.modRequest.projectRoot)
      return config
    },
  ])

  // Step 2 — remove hermesCommand from app/build.gradle (runs via withAppBuildGradle)
  config = withHermesCommandFix(config)

  // Step 3 — gradle.properties safety entries for the main Android project
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
