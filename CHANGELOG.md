# CHANGELOG

<!-- version list -->

## v1.12.0 (2026-10-20)

### Bug Fixes

- Let doorbell alerts interrupt combined displays
  ([#545](https://github.com/worganisation/led-matrix-controller/pull/545),
  [`fd75bd8`](https://github.com/worganisation/led-matrix-controller/commit/fd75bd8682130db1ba0d98ee94fb6a8466772fa8))

- Preserve native submodule build artifacts during deployment
  ([#546](https://github.com/worganisation/led-matrix-controller/pull/546),
  [`6d0bfcd`](https://github.com/worganisation/led-matrix-controller/commit/6d0bfcdca33a655360ff78f08aeb432cf41c50ba))

- Preserve priority when selecting queued combinations
  ([#545](https://github.com/worganisation/led-matrix-controller/pull/545),
  [`fd75bd8`](https://github.com/worganisation/led-matrix-controller/commit/fd75bd8682130db1ba0d98ee94fb6a8466772fa8))

- **ci**: Allow unit test workflow to report PR coverage
  ([#545](https://github.com/worganisation/led-matrix-controller/pull/545),
  [`fd75bd8`](https://github.com/worganisation/led-matrix-controller/commit/fd75bd8682130db1ba0d98ee94fb6a8466772fa8))

- **ci**: Avoid cache writes after container ownership cleanup
  ([#536](https://github.com/worganisation/led-matrix-controller/pull/536),
  [`bba855d`](https://github.com/worganisation/led-matrix-controller/commit/bba855d2f056cd207d531e93eb49233e3276b34e))

- **ci**: Build audio dependencies in the test container
  ([#545](https://github.com/worganisation/led-matrix-controller/pull/545),
  [`fd75bd8`](https://github.com/worganisation/led-matrix-controller/commit/fd75bd8682130db1ba0d98ee94fb6a8466772fa8))

- **ci**: Preserve runner ownership and scope coverage Git trust
  ([#545](https://github.com/worganisation/led-matrix-controller/pull/545),
  [`fd75bd8`](https://github.com/worganisation/led-matrix-controller/commit/fd75bd8682130db1ba0d98ee94fb6a8466772fa8))

- **ci**: Restore checkout ownership and correct coverage arguments
  ([#545](https://github.com/worganisation/led-matrix-controller/pull/545),
  [`fd75bd8`](https://github.com/worganisation/led-matrix-controller/commit/fd75bd8682130db1ba0d98ee94fb6a8466772fa8))

- **ci**: Run benchmarks only in their dedicated workflow
  ([#545](https://github.com/worganisation/led-matrix-controller/pull/545),
  [`fd75bd8`](https://github.com/worganisation/led-matrix-controller/commit/fd75bd8682130db1ba0d98ee94fb6a8466772fa8))

- **ci**: Support source builds and install coverage reporter
  ([#545](https://github.com/worganisation/led-matrix-controller/pull/545),
  [`fd75bd8`](https://github.com/worganisation/led-matrix-controller/commit/fd75bd8682130db1ba0d98ee94fb6a8466772fa8))

- **test**: Stop rain simulation workers after benchmarks
  ([#545](https://github.com/worganisation/led-matrix-controller/pull/545),
  [`fd75bd8`](https://github.com/worganisation/led-matrix-controller/commit/fd75bd8682130db1ba0d98ee94fb6a8466772fa8))

### Chores

- Standardise semantic-release defaults
  ([#544](https://github.com/worganisation/led-matrix-controller/pull/544),
  [`8a155bc`](https://github.com/worganisation/led-matrix-controller/commit/8a155bc77efb5f32a71a95e559416b89a6e5b83f))

- **ci**: Sync shared repository workflows
  ([#536](https://github.com/worganisation/led-matrix-controller/pull/536),
  [`bba855d`](https://github.com/worganisation/led-matrix-controller/commit/bba855d2f056cd207d531e93eb49233e3276b34e))

- **deps**: Configure Renovate updates
  ([#537](https://github.com/worganisation/led-matrix-controller/pull/537),
  [`88cda4a`](https://github.com/worganisation/led-matrix-controller/commit/88cda4a78ee97ac7bbf06a14680b49afed92f8ef))

- **deps**: Update dependency mypy to >=2.4.0,<2.5.0
  ([#543](https://github.com/worganisation/led-matrix-controller/pull/543),
  [`a10fd37`](https://github.com/worganisation/led-matrix-controller/commit/a10fd37815d88c3455b219b859a643f58a92d73f))

- **sync**: Pin github-config-files workflows to 0.7.1
  ([#533](https://github.com/worganisation/led-matrix-controller/pull/533),
  [`08ebe52`](https://github.com/worganisation/led-matrix-controller/commit/08ebe52ad580d4fa99fb34eaef8f6ff73fe10cf5))

- **sync**: Pin github-config-files workflows to 0.8.2
  ([#534](https://github.com/worganisation/led-matrix-controller/pull/534),
  [`3ce4e7c`](https://github.com/worganisation/led-matrix-controller/commit/3ce4e7c8d2b6cecb687c4fcea33ea4c9ca9b673c))

### Code Style

- Fixes from prek hooks ([#536](https://github.com/worganisation/led-matrix-controller/pull/536),
  [`bba855d`](https://github.com/worganisation/led-matrix-controller/commit/bba855d2f056cd207d531e93eb49233e3276b34e))

- Fixes from prek hooks ([#534](https://github.com/worganisation/led-matrix-controller/pull/534),
  [`3ce4e7c`](https://github.com/worganisation/led-matrix-controller/commit/3ce4e7c8d2b6cecb687c4fcea33ea4c9ca9b673c))

- Fixes from prek hooks ([#533](https://github.com/worganisation/led-matrix-controller/pull/533),
  [`08ebe52`](https://github.com/worganisation/led-matrix-controller/commit/08ebe52ad580d4fa99fb34eaef8f6ff73fe10cf5))

### Documentation

- Explain combination identity check
  ([#545](https://github.com/worganisation/led-matrix-controller/pull/545),
  [`fd75bd8`](https://github.com/worganisation/led-matrix-controller/commit/fd75bd8682130db1ba0d98ee94fb6a8466772fa8))

### Features

- Deploy stable matrix releases over shared LAN SSH
  ([#546](https://github.com/worganisation/led-matrix-controller/pull/546),
  [`6d0bfcd`](https://github.com/worganisation/led-matrix-controller/commit/6d0bfcdca33a655360ff78f08aeb432cf41c50ba))

- **ci**: Release manually and deploy published releases
  ([#538](https://github.com/worganisation/led-matrix-controller/pull/538),
  [`912d08f`](https://github.com/worganisation/led-matrix-controller/commit/912d08f23eaa4e1286e91058969f5c4747a2d9d7))

- **ci**: Require manually invoked semantic releases
  ([#538](https://github.com/worganisation/led-matrix-controller/pull/538),
  [`912d08f`](https://github.com/worganisation/led-matrix-controller/commit/912d08f23eaa4e1286e91058969f5c4747a2d9d7))

### Refactoring

- **ci**: Use the unified semantic release runner
  ([#538](https://github.com/worganisation/led-matrix-controller/pull/538),
  [`912d08f`](https://github.com/worganisation/led-matrix-controller/commit/912d08f23eaa4e1286e91058969f5c4747a2d9d7))


## v1.11.2 (2026-08-23)

### Bug Fixes

- Configure semantic release SSH remote
  ([#531](https://github.com/worganisation/led-matrix-controller/pull/531),
  [`47e7f73`](https://github.com/worganisation/led-matrix-controller/commit/47e7f73c8bc30365fa6d47826976fa4b026ce817))

- Configure semantic release SSH remote
  ([#530](https://github.com/worganisation/led-matrix-controller/pull/530),
  [`bf1502b`](https://github.com/worganisation/led-matrix-controller/commit/bf1502bafa8d727c65447ce4fce36532ff232e07))

- Remove erroneous initial release changelog
  ([#531](https://github.com/worganisation/led-matrix-controller/pull/531),
  [`47e7f73`](https://github.com/worganisation/led-matrix-controller/commit/47e7f73c8bc30365fa6d47826976fa4b026ce817))

- Restore MQTT subscriptions after reconnect
  ([#526](https://github.com/worganisation/led-matrix-controller/pull/526),
  [`e0d3a72`](https://github.com/worganisation/led-matrix-controller/commit/e0d3a72239732105229dd1d3c49e3a83dca5eb8b))

- Restore MQTT subscriptions after reconnect
  ([#524](https://github.com/worganisation/led-matrix-controller/pull/524),
  [`d32b046`](https://github.com/worganisation/led-matrix-controller/commit/d32b046c2aba4cab2d87bc316dad4988ec5c204f))

- Use deploy key for semantic release pushes
  ([#529](https://github.com/worganisation/led-matrix-controller/pull/529),
  [`182a0c5`](https://github.com/worganisation/led-matrix-controller/commit/182a0c504a0986930f27ac9d141a680ed31e863d))

- **actions**: Remove unsupported reusable input
  ([#523](https://github.com/worganisation/led-matrix-controller/pull/523),
  [`41c2984`](https://github.com/worganisation/led-matrix-controller/commit/41c2984e36fcb1fd521456d1a7f8e989d79c9ffb))

- **actions**: Repair auto-create-pr workflows
  ([#523](https://github.com/worganisation/led-matrix-controller/pull/523),
  [`41c2984`](https://github.com/worganisation/led-matrix-controller/commit/41c2984e36fcb1fd521456d1a7f8e989d79c9ffb))

- **actions**: Update reusable workflow owner
  ([#523](https://github.com/worganisation/led-matrix-controller/pull/523),
  [`41c2984`](https://github.com/worganisation/led-matrix-controller/commit/41c2984e36fcb1fd521456d1a7f8e989d79c9ffb))

- **ci**: Remove superseded snake case workflows
  ([#518](https://github.com/worganisation/led-matrix-controller/pull/518),
  [`7dd3e87`](https://github.com/worganisation/led-matrix-controller/commit/7dd3e870d3ac0cb3ccb73af03811596daa2a884a))

- **ci**: Skip uv setup for Poetry project
  ([#518](https://github.com/worganisation/led-matrix-controller/pull/518),
  [`7dd3e87`](https://github.com/worganisation/led-matrix-controller/commit/7dd3e870d3ac0cb3ccb73af03811596daa2a884a))

- **ci**: Use migrated reusable workflows
  ([#518](https://github.com/worganisation/led-matrix-controller/pull/518),
  [`7dd3e87`](https://github.com/worganisation/led-matrix-controller/commit/7dd3e870d3ac0cb3ccb73af03811596daa2a884a))

### Chores

- Address uv migration review feedback
  ([#527](https://github.com/worganisation/led-matrix-controller/pull/527),
  [`f7bf37e`](https://github.com/worganisation/led-matrix-controller/commit/f7bf37e2e5e07d0b8696af2d23f0b6f8651dca08))

- Migrate dependency management to uv
  ([#527](https://github.com/worganisation/led-matrix-controller/pull/527),
  [`f7bf37e`](https://github.com/worganisation/led-matrix-controller/commit/f7bf37e2e5e07d0b8696af2d23f0b6f8651dca08))

- **sync**: Pin github-config-files workflows to 0.6.0
  ([#518](https://github.com/worganisation/led-matrix-controller/pull/518),
  [`7dd3e87`](https://github.com/worganisation/led-matrix-controller/commit/7dd3e870d3ac0cb3ccb73af03811596daa2a884a))

### Code Style

- Simplify docstring phrasing
  ([`d203e26`](https://github.com/worganisation/led-matrix-controller/commit/d203e26f81b4fdc2411c9dbbfaee8e5b265744c7))

### Continuous Integration

- Let semantic release own deployment
  ([#526](https://github.com/worganisation/led-matrix-controller/pull/526),
  [`e0d3a72`](https://github.com/worganisation/led-matrix-controller/commit/e0d3a72239732105229dd1d3c49e3a83dca5eb8b))

- Remove legacy validation workflow
  ([#526](https://github.com/worganisation/led-matrix-controller/pull/526),
  [`e0d3a72`](https://github.com/worganisation/led-matrix-controller/commit/e0d3a72239732105229dd1d3c49e3a83dca5eb8b))


## v1.11.1 (2026-07-20)

### Bug Fixes

- Handle tick condition safely with try-finally
  ([#497](https://github.com/worganisation/led-matrix-controller/pull/497),
  [`731ffcd`](https://github.com/worganisation/led-matrix-controller/commit/731ffcd57e793547b6ed0a7b9e35f4a78adc7d47))

- Safeguard tick condition with try-finally
  ([#498](https://github.com/worganisation/led-matrix-controller/pull/498),
  [`740a33f`](https://github.com/worganisation/led-matrix-controller/commit/740a33fdc61cf19a44a9e77aa0d165e21646032d))


## v1.11.0 (2025-12-30)


## v1.10.0 (2025-11-20)


## v1.9.0 (2025-05-10)


## v1.8.1 (2025-05-10)


## v1.8.0 (2024-12-01)


## v1.7.2 (2024-11-23)


## v1.7.1 (2024-10-20)


## v1.7.0 (2024-09-15)


## v1.6.1 (2024-09-03)


## v1.6.0 (2024-08-29)


## v1.5.0 (2024-08-18)

### Features

- Add clock content ([#283](https://github.com/worganisation/led-matrix-controller/pull/283),
  [`ff99288`](https://github.com/worganisation/led-matrix-controller/commit/ff992888ad6cd81c0aea14e6b7219c52f0ae18c8))


## v1.4.1 (2024-08-08)


## v1.4.0 (2024-07-21)


## v1.3.0 (2024-07-06)


## v1.2.2 (2024-07-01)


## v1.2.1 (2024-05-18)


## v1.2.0 (2024-05-12)


## v1.1.0 (2024-05-11)


## v1.0.0 (2024-04-27)


## v0.2.1 (2024-03-10)


## v0.2.0 (2024-03-06)


## v0.1.5 (2024-03-03)


## v0.1.4 (2024-03-03)


## v0.1.3 (2024-03-03)


## v0.1.2 (2024-03-03)


## v0.1.1 (2024-03-03)


## v0.1.0 (2023-10-22)

- Initial Release
