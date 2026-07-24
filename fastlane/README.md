fastlane documentation
----

# Installation

Make sure you have the latest version of the Xcode command line tools installed:

```sh
xcode-select --install
```

For _fastlane_ installation instructions, see [Installing _fastlane_](https://docs.fastlane.tools/#installing-fastlane)

# Available Actions

### test

```sh
[bundle exec] fastlane test
```



### beta

```sh
[bundle exec] fastlane beta
```



### release

```sh
[bundle exec] fastlane release
```



### screenshots

```sh
[bundle exec] fastlane screenshots
```



### certs

```sh
[bundle exec] fastlane certs
```

Generate distribution cert + provisioning profile via match

### bootstrap

```sh
[bundle exec] fastlane bootstrap
```

First-time setup. Documents what user needs to do.

### build

```sh
[bundle exec] fastlane build
```

Debug build with no signing (local dev)

### build_release

```sh
[bundle exec] fastlane build_release
```

Release build, signed with match, not notarized

### snapshot

```sh
[bundle exec] fastlane snapshot
```

Generate App Store screenshots

### build_daemon

```sh
[bundle exec] fastlane build_daemon
```

Build the volta-daemon with PyInstaller and codesign

----

This README.md is auto-generated and will be re-generated every time [_fastlane_](https://fastlane.tools) is run.

More information about _fastlane_ can be found on [fastlane.tools](https://fastlane.tools).

The documentation of _fastlane_ can be found on [docs.fastlane.tools](https://docs.fastlane.tools).
