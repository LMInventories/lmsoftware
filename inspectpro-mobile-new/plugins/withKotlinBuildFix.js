/**
 * withKotlinBuildFix.js
 *
 * Expo config plugin that patches android/gradle.properties so that:
 *
 *   1. kotlin.compiler.execution.strategy=in-process
 *      Forces the Kotlin compiler to run inside the Gradle daemon JVM rather
 *      than spawning a separate worker JVM. Fixes the Internal compiler error
 *      on ':gradle-plugin:settings-plugin:compileKotlin' (React Native's
 *      Gradle settings plugin compiled with Kotlin 2.0 + KGP Worker API).
 *
 *   2. org.gradle.jvmargs includes -Dkotlin.compiler.execution.strategy=in-process
 *      The JVM arg form is what actually reaches the Gradle daemon. The daemon
 *      hosts ALL tasks including composite/included build tasks (like the RN
 *      settings-plugin), so this ensures the property is visible to every
 *      Kotlin compilation that happens in the build.
 *
 *   3. org.gradle.daemon=false
 *      Each EAS build starts from scratch, so the daemon offers no warm-up
 *      benefit. Disabling it avoids any stale daemon state.
 *
 * Why not GRADLE_OPTS in eas.json?
 *   GRADLE_OPTS sets JVM args on the Gradle CLIENT process (the one that reads
 *   args and starts the daemon). The actual compilation runs in the DAEMON
 *   (or in workers spawned from it), which is controlled by org.gradle.jvmargs
 *   in gradle.properties — not GRADLE_OPTS.
 */

const { withGradleProperties } = require('@expo/config-plugins')

/**
 * Set or replace a property in the gradle.properties mod results array.
 */
function setProp(props, key, value) {
  const existing = props.find(p => p.type === 'property' && p.key === key)
  if (existing) {
    existing.value = value
  } else {
    props.push({ type: 'property', key, value })
  }
}

/**
 * Merge new JVM args into an existing org.gradle.jvmargs string.
 * Avoids duplicating flags that are already present.
 */
function mergeJvmArgs(existing, ...toAdd) {
  let base = existing || '-Xmx4096m -XX:MaxMetaspaceSize=1g -Dfile.encoding=UTF-8'
  for (const arg of toAdd) {
    // Extract the -D key (e.g. -Dkotlin.compiler.execution.strategy)
    const key = arg.match(/^-D([^=]+)/)?.[1]
    if (key && base.includes(`-D${key}`)) {
      // Replace existing value
      base = base.replace(new RegExp(`-D${key}=[^\\s]*`), arg)
    } else if (!base.includes(arg)) {
      base = `${base} ${arg}`
    }
  }
  return base
}

module.exports = function withKotlinBuildFix(config) {
  return withGradleProperties(config, (config) => {
    const props = config.modResults

    // 1. Direct Gradle property form — read by KGP during task configuration
    setProp(props, 'kotlin.compiler.execution.strategy', 'in-process')

    // 2. Daemon JVM args — these reach all tasks running inside the daemon,
    //    including composite/included build tasks like RN's settings-plugin.
    const existing = props.find(p => p.type === 'property' && p.key === 'org.gradle.jvmargs')
    const merged = mergeJvmArgs(
      existing?.value,
      '-Dkotlin.compiler.execution.strategy=in-process',
      '-Dkotlin.daemon.enabled=false',
    )
    setProp(props, 'org.gradle.jvmargs', merged)

    // 3. Disable daemon — EAS builds are stateless so no warm-up benefit
    setProp(props, 'org.gradle.daemon', 'false')

    return config
  })
}
