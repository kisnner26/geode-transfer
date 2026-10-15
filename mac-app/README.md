# geode transfer for mac

Native macOS interface for the `geode_transfer.py` engine. It keeps the command-line tool as the transfer authority and invokes it with stable device identifiers.

## run locally

```sh
cd mac-app
swift run
```

The app locates `../geode_transfer.py` during development. For another location, set `GEODE_TRANSFER_CLI` to the absolute path of that file before launching.

## install

```sh
./scripts/install-app.sh
```

This builds a release app at `~/Applications/Geode Transfer.app`, bundles the Python engine and opens it.

The app requires macOS 26, Xcode 27 and the same connected, unlocked development-signed devices required by the CLI.
