# Changelog

All notable changes to SetVault are documented here. Format adheres to
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.25.0](https://github.com/bardesss/setvault/compare/v0.24.0...v0.25.0) (2026-10-28)


### Features

* **api:** playlists and synced play queue endpoints ([1021e28](https://github.com/bardesss/setvault/commit/1021e28328e797775d469bc80e2d43ac1766957c))
* **api:** webhook secrets shown once, masked headers, validation, delivery log ([c8da51a](https://github.com/bardesss/setvault/commit/c8da51a241e9c028f3ee0eae1f3a502bdff31926))
* **core:** encrypted webhook headers and secrets, delivery log table ([15dbd5c](https://github.com/bardesss/setvault/commit/15dbd5c7ab63e59cb1afbdfadde87d0fe1efb962))
* **core:** playlists and play queue models, services and merge re-point ([37d2374](https://github.com/bardesss/setvault/commit/37d2374a23afbc9eb17f76e5e3ab2b5e94a2277b))
* **core:** sign, log and retry webhook deliveries ([9b95339](https://github.com/bardesss/setvault/commit/9b95339a5e974900a5708a8bfddbff6d28e87709))
* fire set.updated, set.deleted, set.restored and set.purged webhooks ([e75995a](https://github.com/bardesss/setvault/commit/e75995a655930c7fc42d1df87fd9eb5f54e213a3))
* P4a webhook hardening (signing, encrypted headers, retries, delivery log, more events) ([8276f17](https://github.com/bardesss/setvault/commit/8276f175a5daabb893090638d8e0538e2eadcdf4))
* P4b playlists and a cross-device play queue ([9ba17ba](https://github.com/bardesss/setvault/commit/9ba17bae90b622d315a3d2427b3f9168058eae7d))
* **player:** cross-set play queue with auto-advance ([d7ad7f0](https://github.com/bardesss/setvault/commit/d7ad7f07cb82830fb77822baf2dc20e27ecc9da9))
* **player:** sync the play queue across devices ([907ed5f](https://github.com/bardesss/setvault/commit/907ed5f308b01e44c6794e2c4575bb6de4b92115))
* **web:** playlists pages and add-to-playlist menu ([47f6b48](https://github.com/bardesss/setvault/commit/47f6b48a88c116f03064887d81bddab201772ab8))
* **web:** webhooks page with secrets, masked headers and delivery log ([65a4c88](https://github.com/bardesss/setvault/commit/65a4c88800efac9d03850d52953024d190b8ab8c))


### Bug Fixes

* **core:** empty reorder, naive queue base time, ordering ties and test gaps ([f15cde8](https://github.com/bardesss/setvault/commit/f15cde8610575626a6b227ead427b36e23c695eb))
* **core:** real RQ retry test, permanent bad-URL failures, safer delete re-check ([a78cdea](https://github.com/bardesss/setvault/commit/a78cdead024833fe9c865ccceee2bd039207aa5f))
* **player:** clear lock-screen metadata on logout, correct reset comment ([24ed9dd](https://github.com/bardesss/setvault/commit/24ed9dd3a84b39a00bda4e0fa44663917a522976))
* **player:** final P4b review fixes ([e7d8f5b](https://github.com/bardesss/setvault/commit/e7d8f5bdc671ebbbe1a312a44900c7ac9a5d7e1a))
* **player:** queue sync races, auth scoping and resume semantics ([08e99fe](https://github.com/bardesss/setvault/commit/08e99fe7861040323122a39a2775ce76564f0c9d))
* **player:** scope the stored queue to its user and stop advances on logout ([240df04](https://github.com/bardesss/setvault/commit/240df042548a808f290cc94bbfde6276c198e676))
* **player:** set-page controls respect the current set; queue race and index fixes ([3b45630](https://github.com/bardesss/setvault/commit/3b456301c118bb6ebd44dbed3f678f3085c453ae))
* real titles in recycle events, cover upgrade swap and draft sites ([8052ebf](https://github.com/bardesss/setvault/commit/8052ebf4f70f12f868713e5fe47784137e99fb66))
* **webhooks:** drop stored framing headers, allow removing reserved names, accept tabs ([e4b57bd](https://github.com/bardesss/setvault/commit/e4b57bdc47e89ac0266eef674b8c62e4f81857e6))
* **webhooks:** harden headers, undecryptable data and job edge cases ([4c1b841](https://github.com/bardesss/setvault/commit/4c1b841104dd1fa9bfd713121fc59022ba19437f))

## [0.24.0](https://github.com/bardesss/setvault/compare/v0.23.0...v0.24.0) (2026-10-26)


### Features

* **admin:** YouTube cookies upload on Admin -&gt; Sources ([1b56774](https://github.com/bardesss/setvault/commit/1b567743c096a7485d17d7f6af143732c048b100))
* **core:** send uploaded YouTube cookies with every yt-dlp call ([18c2549](https://github.com/bardesss/setvault/commit/18c2549f203390ef5fb5c97c2c80b4773c1bc777))
* get YouTube past the bot check (EJS + PO tokens, cookies upload fallback) ([665cef3](https://github.com/bardesss/setvault/commit/665cef3063be0c3d94b3c69a3119547f7419cb6c))


### Bug Fixes

* address final P3 review ([ee5ba39](https://github.com/bardesss/setvault/commit/ee5ba3969129ab4fe397592c78ed1cedf685c6c5))
* **rips:** rate-limit and audit discovery rips; report throttled sources; skip disabled users' monitors ([44128d7](https://github.com/bardesss/setvault/commit/44128d7b7cc9992caef30cf4ee7137cebfdc15be))


### Refactors

* one slugify, one enqueue_email, one redis_url helper ([e38c596](https://github.com/bardesss/setvault/commit/e38c5962c5e766762419ddcedcb3afaf8e0f163e))
* remove dead Python code; rehash outdated passwords on login ([93a2e17](https://github.com/bardesss/setvault/commit/93a2e175cf1f1835bbd40e80560df813ddfc416b))
* share schedule, trigger and fingerprint definitions; one upgrade-event builder ([9d400ed](https://github.com/bardesss/setvault/commit/9d400edf6e93ec9f483ea53e0f871b3aa0e236b0))
* **web:** remove dead client code, unused i18n keys and tokens; allow any orientation ([67aceab](https://github.com/bardesss/setvault/commit/67aceab49b0cdb7e017ec31fd307242430ab1b96))
* **web:** shared duration/bytes/date formatters; root error page ([dbacebe](https://github.com/bardesss/setvault/commit/dbacebe86767c7a5bfc3bee0b62128fd20e4a261))


### Documentation

* bring README, site, env and compose docs up to date; CI on PG18 ([6bbbf40](https://github.com/bardesss/setvault/commit/6bbbf4007683db10e5d1bbccc86498de9b0c7440))
* list pot-provider in the image header; bump .env.example to 0.23.0 ([d9f67e6](https://github.com/bardesss/setvault/commit/d9f67e6cf7af404aeac5997da6db64e8da35241c))
* **readme:** YouTube sign-in / bot check ([14ec0dd](https://github.com/bardesss/setvault/commit/14ec0ddbec51daa82d01d36719384c875a215fb8))

## [0.23.0](https://github.com/bardesss/setvault/compare/v0.22.0...v0.23.0) (2026-10-25)


### Features

* **admin:** Drafts tab to publish or discard unpublished sets ([f0d1d07](https://github.com/bardesss/setvault/commit/f0d1d07455cfbaa27c584123302749940a45f8e8))


### Bug Fixes

* probe failures are a 400, and Home counts published sets only ([07016ae](https://github.com/bardesss/setvault/commit/07016ae9de2316ec80a4b3df23739364b66bb871))
* probe failures are a 400; Home counts published sets; Admin Drafts tab ([d4e87d4](https://github.com/bardesss/setvault/commit/d4e87d455e14ea956f572ad8f05c3b356588f954))

## [0.22.0](https://github.com/bardesss/setvault/compare/v0.21.0...v0.22.0) (2026-10-24)


### Features

* **catalog:** browse lists, paged entity sets and a track filter ([936b66c](https://github.com/bardesss/setvault/commit/936b66c8592dff000fcfb4aa57e35e7410670bd9))
* **health:** check db and redis; admin-only entity actions ([078f8a9](https://github.com/bardesss/setvault/commit/078f8a9b64ab9d4c4b8cf4c56a1ee404a32bef93))
* **home:** recent activity list ([c8bd806](https://github.com/bardesss/setvault/commit/c8bd806d7226df4f60c3b3c7f9818ff541957b79))
* P2b browse pages, home activity, health endpoint, entity role gating ([0e0e104](https://github.com/bardesss/setvault/commit/0e0e104266bb49eea42cfde6f431eb9e056338c2))
* **storage:** record set sizes and show real audio storage on Home ([2327b08](https://github.com/bardesss/setvault/commit/2327b081be237baf77f697d3dde82d7f4492f42e))
* **ui:** browse pages, track link and load-more on entity pages ([08c907c](https://github.com/bardesss/setvault/commit/08c907c218a152af9e43162b2164003b17bddbb0))


### Bug Fixes

* **browse,home:** final review fixes ([d806a95](https://github.com/bardesss/setvault/commit/d806a95ebfb1b785dc5c890b2acb0e2b5c14b7d3))
* **health:** log failed checks; add unreachable-redis test ([9f7c349](https://github.com/bardesss/setvault/commit/9f7c349b27a43fbc65758aa4c4812906667e6afe))
* **home:** unique activity item ids and populated e2e ([551735e](https://github.com/bardesss/setvault/commit/551735e209c26d753e7f3d073836db8e228e75ba))
* **storage:** bound the worker-start size check and dedupe the backfill ([66a8407](https://github.com/bardesss/setvault/commit/66a8407385407d1ef3a7d5902119d9ee802dda46))

## [0.21.0](https://github.com/bardesss/setvault/compare/v0.20.0...v0.21.0) (2026-10-24)


### Features

* **admin:** edit and probe media roots, preview naming, edit and delete SMTP connector ([37c0b95](https://github.com/bardesss/setvault/commit/37c0b9511f86f4e649fd1c5f3aa0b0d4fade8143))
* **audio:** apply static loudness gain at transcode with a library re-gain job ([aff24cd](https://github.com/bardesss/setvault/commit/aff24cda234fde340ce8923461907df36bf86073))
* **backup:** nightly gzipped database backups with retention, API and restore ([47efe99](https://github.com/bardesss/setvault/commit/47efe99a84c43620bc7190aa543cf186459c2837))
* **cli:** reset_password command for a locked-out admin ([38dbbdd](https://github.com/bardesss/setvault/commit/38dbbdd2cab604036d4984b4716573469c56dc08))
* **db:** add P2a columns (0033_p2a) ([906029a](https://github.com/bardesss/setvault/commit/906029ac89f386ae916a1567cc7a1bfd6df75a71))
* **monitors:** link query monitors to catalog entities, edit in place, audit ([a3c1c9b](https://github.com/bardesss/setvault/commit/a3c1c9b43832aec713a1160974718d8e99de7ade))
* **naming:** apply the root's naming template at publish, after upgrades, and per set ([f4ba7a1](https://github.com/bardesss/setvault/commit/f4ba7a1ccbdc23fb0c3511d74ac1a93d4953da8b))
* P2a must-haves (set editor, monitors, loudness, naming, backups, storage/email) ([f108191](https://github.com/bardesss/setvault/commit/f10819168816b85f07c5828a29465a0fc09d1454))
* **sets:** edit artist roles, clear fields, audit edits; add catalog lookup ([e0cd10a](https://github.com/bardesss/setvault/commit/e0cd10a5979ab8e242ca5b0a72ed9e69e8d43474))
* **ui:** add Modal, ConfirmDialog, toasts and EntityPicker ([5b1d070](https://github.com/bardesss/setvault/commit/5b1d070c26e582b75c3fd822b49be8eafb6cc4d7))
* **ui:** admin backups tab ([2e744e6](https://github.com/bardesss/setvault/commit/2e744e6bbf4f8c2df17cf447bc9787cd608f1e27))
* **ui:** editable storage roots and an email settings tab ([1c40898](https://github.com/bardesss/setvault/commit/1c4089808f96faa22b7a6490feb298d9717e2003))
* **ui:** loudness target setting, library re-gain, offline audio fallback ([6df913e](https://github.com/bardesss/setvault/commit/6df913e29f7004230a6e41dad677932638d8aca2))
* **ui:** monitor from entity pages, full monitor form, discoveries in nav ([3b17a82](https://github.com/bardesss/setvault/commit/3b17a82ec116d759620ca115b7282308d0822237))
* **ui:** set metadata editor ([c4f759a](https://github.com/bardesss/setvault/commit/c4f759aed336913221129c19e15d87773140284f))


### Bug Fixes

* **backup:** keep an existing dir's mode; report an unreadable backup dir ([42ee416](https://github.com/bardesss/setvault/commit/42ee416c07a8e43a48364efc97cdba113b28d1b3))
* **backup:** owner-only files, one failure notice per day, no overwrite, mtime pruning ([1ec1474](https://github.com/bardesss/setvault/commit/1ec1474d9c6c24e54ccddd5b7b4bedc1634273da))
* **bulk:** place move-root copies by exclusive create and tidy created dirs ([26bb837](https://github.com/bardesss/setvault/commit/26bb837cf482a88ef96a1594d17b6d21eb591125))
* **media:** queue a stream for restored sets and re-check move-root under lock ([12ee36f](https://github.com/bardesss/setvault/commit/12ee36faa1377d2dd9ba0071078219333e85dff0))
* **merge:** keep monitoring when the dropped loser monitor was active ([2bb0769](https://github.com/bardesss/setvault/commit/2bb0769edc0199fe060e3424a47df51f4f015795))
* **naming:** exclusive-create renames and row-locked re-apply ([4c348dd](https://github.com/bardesss/setvault/commit/4c348dd554427c37b202f558b74728a2b4e4bacb))
* **sets:** audit set.edited with target_type LiveSet like the other set audits ([bb3db12](https://github.com/bardesss/setvault/commit/bb3db12b5af53427606f0ca8b745181a86d2772e))
* **transcode:** never overwrite a stream another row references ([251ffb1](https://github.com/bardesss/setvault/commit/251ffb1535f5edf01572dc133ac1fc12ff9a613f))
* **transcode:** re-check the row under lock before swapping in a new stream ([8c99585](https://github.com/bardesss/setvault/commit/8c9958570847bb5c2cca82c7a0f41e49e6d36029))
* **transcode:** re-encode after a rename or root move instead of discarding ([0ae872b](https://github.com/bardesss/setvault/commit/0ae872be5328749c71588f236b0c75c7e9ede9de))
* **ui:** deflake loudness e2e, stub re-gain, keep fresh audio on cache errors ([ac1f987](https://github.com/bardesss/setvault/commit/ac1f9870a70ce5df1c5c686b27d7ee0c875f97fd))
* **ui:** discoveries badge store, ingested tab, i18n regression ([5ff9325](https://github.com/bardesss/setvault/commit/5ff9325f5af67f3f8e28a9e3bf89efc3679ebeed))
* **ui:** harden EntityPicker lookups and stack Modal escape handling ([fbea89e](https://github.com/bardesss/setvault/commit/fbea89eee2c234e8e59a97d4b60c9357ef581bb8))
* **ui:** own-connector cleanup in email e2e, health badge variants, GiB label ([c7b4b31](https://github.com/bardesss/setvault/commit/c7b4b31dedb10f0b3151b54469658d51948f0ec7))
* **ui:** treat a 404 on monitor delete as stopped ([ba89e1a](https://github.com/bardesss/setvault/commit/ba89e1a05132036a72bf7bd5ac8522cf961cc8ea))

## [0.20.0](https://github.com/bardesss/setvault/compare/v0.19.1...v0.20.0) (2026-10-22)


### Features

* **api:** favourite sets ([c730776](https://github.com/bardesss/setvault/commit/c73077634795a822179fdc8bb1fad5d08bbcb434))
* **api:** filter, sort and page the set list; add list facets ([93a9355](https://github.com/bardesss/setvault/commit/93a93556c047295e5a3b47320e53183eb4916dbe))
* **providers:** enrich artists from MusicBrainz and Discogs ([48589f9](https://github.com/bardesss/setvault/commit/48589f9534ed05dd4db461d8b89cb98da7820136))
* **web:** favourite button, favourites page and nav link ([6f637ef](https://github.com/bardesss/setvault/commit/6f637ef0e41d6db1439c31db274249bc5dbd201e))
* **worker:** record each background job run for Admin → Jobs ([c603a66](https://github.com/bardesss/setvault/commit/c603a663bddc40d6a617abadc4d6fb3b5ec4d049))


### Bug Fixes

* absolute feed and email links; copy works on plain HTTP ([6be6af6](https://github.com/bardesss/setvault/commit/6be6af65a4352b4581d7c39f938e3dd2d3d8eaf9))
* **api:** party patch validates venue/series; i18n key only in en.json ([14062f6](https://github.com/bardesss/setvault/commit/14062f6345c3009668cb93fdc963fd8723c48715))
* **api:** tracklist imports accept once; malformed ids and tag/artist edits never 500 ([9895f6b](https://github.com/bardesss/setvault/commit/9895f6bb98f86ff82974133b2dbcb7bc38ff4e31))
* bulk move-root moves set files and commits per set ([2f7849b](https://github.com/bardesss/setvault/commit/2f7849bfa93af0ce98537690492eeb9e7a18fcde))
* **catalog:** dedup key tolerates a name starting with a combining mark ([de57abf](https://github.com/bardesss/setvault/commit/de57abfcd520aad68a48bb57b5767806385078ea))
* **catalog:** enrichment resolves merged artists to survivors; safer unmerge and dedup keys ([1ae8c23](https://github.com/bardesss/setvault/commit/1ae8c230b98aba26e7d9b928fd4d324a42eba578))
* **catalog:** safe audit payloads, merge dedupes tracks, unicode-aware dedup and unique slugs ([f0cc65f](https://github.com/bardesss/setvault/commit/f0cc65f16638ff631d84e8d14579eb1b5954876b))
* discovery rips survive, failed polls are recorded, rate-limit edits keep source health ([f0b1cc8](https://github.com/bardesss/setvault/commit/f0b1cc83107143817173a9abe08f649d1f6b6664))
* **docker:** clearer secrets errors; repair keeps unmatched files with their folder ([e9ae799](https://github.com/bardesss/setvault/commit/e9ae799973d0b3d02e20c32953ab5f31bda08bb5))
* keepalive pagehide save, MusicBrainz 1 req/s throttle, sets URL param hardening ([b515c04](https://github.com/bardesss/setvault/commit/b515c0424229371b993caddba6eb49ca4f3b61c4))
* only save playback state while playing; continue-listening ignores unplayed sets ([247f5aa](https://github.com/bardesss/setvault/commit/247f5aa8e621dc3f9c37bfd8e19b37d7e282a13c))
* P1 functional fixes ([9bafec8](https://github.com/bardesss/setvault/commit/9bafec880f65067c01a85b83c217ec857b0e8fc1))
* **pwa:** keep offline audio across updates and remember the size cap ([7581580](https://github.com/bardesss/setvault/commit/75815803f4eade0bed45d4944dddb4a273109029))
* **quality:** wanted matches the scheduler, duplicate scan runs in the worker, swaps shift duplicate offsets ([172e7d1](https://github.com/bardesss/setvault/commit/172e7d1288e8f2cc7ca850c20162896a6c54b995))
* **quality:** wanted page points to the backfill; post-cleanup scan is queued ([fbe3cea](https://github.com/bardesss/setvault/commit/fbe3cea09d14fe483bd45ab4d53197a27287f62e))
* report the real version from package metadata ([f8ebc85](https://github.com/bardesss/setvault/commit/f8ebc85862df5c9d70b93634c11eb30f9ba17905))
* **web:** align shortcut role lists with spec and resolve composed target ([a9ea411](https://github.com/bardesss/setvault/commit/a9ea411e5a778ad68f522c39566e405d1b707c91))
* **web:** library pages beyond 50 sets and the filters work ([76e1a5e](https://github.com/bardesss/setvault/commit/76e1a5e3b3e3358e95579772d1313aaa70a92fa5))
* **web:** player shortcuts ignore modified keys, form fields and focused controls ([ab1c537](https://github.com/bardesss/setvault/commit/ab1c53759d4afdee015b8f944ade382d084f18a1))
* **web:** use bg-base for unread badge text for AA contrast ([6206c1b](https://github.com/bardesss/setvault/commit/6206c1bc4d8b9c06a02d1ed7fb62c58e356d9f11))
* **web:** use defined theme tokens for panels, inputs and error text ([459c7de](https://github.com/bardesss/setvault/commit/459c7de3d82109e416ecfab1c36e7f1f64b809db))
* **worker:** allowlist job payloads and never reuse a previous run's row ([7ac6e3a](https://github.com/bardesss/setvault/commit/7ac6e3a4bdfb16b8fa8089e4bf920dfa8c0144ee))


### Performance

* **web:** draw the waveform from precomputed peaks ([128091e](https://github.com/bardesss/setvault/commit/128091e7e015effc80fc6ad6836919b09fd4e4fc))

## [0.19.1](https://github.com/bardesss/setvault/compare/v0.19.0...v0.19.1) (2026-10-21)


### Bug Fixes

* **auth:** enforce 12-char minimum on invite redeem and avoid 500 on invite collisions ([743374c](https://github.com/bardesss/setvault/commit/743374cce6b6fdff3a487628aaa85f3010d8d0ad))
* **auth:** revoke sessions on disable, password change or reset, and admin reset links ([6c9452c](https://github.com/bardesss/setvault/commit/6c9452cb8b3d343ff8f2f39a3d9e99889c782fe8))
* **auth:** version session cookies and check user status on stream, waveform, WS and upload hooks ([4d5a12a](https://github.com/bardesss/setvault/commit/4d5a12a18aa933ac44a047e1555c44af202362c1))
* **docker:** clear a stale postmaster.pid left by an unclean stop ([eb14541](https://github.com/bardesss/setvault/commit/eb14541853a6c7e285c4c93c5f50644a4f4d8e9a))
* **docker:** fail boot on a rejected persisted secret instead of replacing it ([d77e4c8](https://github.com/bardesss/setvault/commit/d77e4c8e49089bcdca4c5d67d361ce08f743f4f8))
* **docker:** keep bundled data under /data and harden secrets handling ([084a8cc](https://github.com/bardesss/setvault/commit/084a8cca52af449ea4d1c0c4d596567ec440797b))
* **docker:** only clear postmaster.pid in the PID-reuse case ([7e732cc](https://github.com/bardesss/setvault/commit/7e732cc6fc5cfe2125cd59a0fe0658fee9d7bbe5))
* **migrations:** escape % in DATABASE_URL for alembic config ([0467456](https://github.com/bardesss/setvault/commit/0467456df36d58e3cffa2f6a04529f9d0d6287fa))
* P0 data safety and security ([0d1ff7e](https://github.com/bardesss/setvault/commit/0d1ff7e3b6897387694061284ec24dfc7e39c11c))
* **pwa:** never cache admin responses; backup is no-store ([a161fe4](https://github.com/bardesss/setvault/commit/a161fe40c0308754acc8a75e1108129938718e33))
* **sources:** reject a zero rate-limit window and clamp bad stored values ([035872c](https://github.com/bardesss/setvault/commit/035872ca853d9df64cd939b490e5d5d72af0c3e7))
* **storage:** apply every legacy pair to all path targets, audit as system.paths_repaired, report sub-path roots ([0356c66](https://github.com/bardesss/setvault/commit/0356c66259d0e1aa2b505af209e3df120b79bb8c))
* **storage:** leave rows under a live /srv sub-mount alone in the legacy repair ([7d3c608](https://github.com/bardesss/setvault/commit/7d3c6087eefe0c41113634437d76984759fd8829))
* **storage:** name the effective media path and the README in the damage warning ([565b092](https://github.com/bardesss/setvault/commit/565b09294bcd4b5ed89965be58c687a8e65d3453))
* **storage:** repair legacy /srv paths in the DB on boot and report missing set files ([cd60615](https://github.com/bardesss/setvault/commit/cd60615a7537a74125cd84e0390f77b296591f90))
* **storage:** skip watch-folder rows whose repaired path is already taken ([f5a2327](https://github.com/bardesss/setvault/commit/f5a2327aa3fbc30409d4e8725c461fcb52a2d69c))


### Documentation

* bundled upgrade rescue step for data in /srv ([f884692](https://github.com/bardesss/setvault/commit/f88469229b5ee2e5f39b94fe09fc497b304431fb))
* note that an env SECRET_KEY now overrides the persisted one ([fdee628](https://github.com/bardesss/setvault/commit/fdee628358c83fc203921c83a91f867a14440b41))

## [0.19.0](https://github.com/bardesss/setvault/compare/v0.18.0...v0.19.0) (2026-10-21)


### Features

* **backfill:** retry failed sets and run one backfill chain at a time ([b4d05c6](https://github.com/bardesss/setvault/commit/b4d05c697fad41fda67fe15926b4025760db17c6))
* **db:** widen set_upgrade_events.trigger to 32 characters ([dfd9e31](https://github.com/bardesss/setvault/commit/dfd9e3162b50dc7125b43a85d675bf0da4684970))
* **web:** Quality tab shows failed backfill sets, offers retry, and reports an already-running backfill ([7192b8c](https://github.com/bardesss/setvault/commit/7192b8c09083c5e00396735be91aef4222b0ba9d))


### Bug Fixes

* **audit:** kept-arrival audit names the recycled original, not duplicate_of ([96e2ff4](https://github.com/bardesss/setvault/commit/96e2ff4522d70aaf5d3c6e1da5d374ea62ad7a87))
* **backfill:** lock around the in-flight check and enqueue; review minors ([399b976](https://github.com/bardesss/setvault/commit/399b97639a8cea3fa37a89323d853eff7742170a))
* **backfill:** skip a set hard-deleted during fpcalc; inject the clock ([bfe65c3](https://github.com/bardesss/setvault/commit/bfe65c38fed3c44ff1432448e65e5c4471d5dc57))
* **fingerprint:** don't hold a DB connection across fpcalc or compares ([d5006b0](https://github.com/bardesss/setvault/commit/d5006b00b895de77df55e0c0515d620fbd243dc0))
* **frontend:** drop invalid selector list around the light-theme [@media](https://github.com/media) block ([4415b1f](https://github.com/bardesss/setvault/commit/4415b1f0622ad2837040340ba6003bf874977213))
* **internet-archive:** _has_flac tolerates any format shape ([7178558](https://github.com/bardesss/setvault/commit/7178558b77b963e030cce9284888741782b52bba))
* **purge:** remove now-empty originals/ dirs of every deleted file ([aae0bcd](https://github.com/bardesss/setvault/commit/aae0bcdfd98835da2bf586718b485b6e5605a6e3))
* **quality:** 7D follow-ups — robustness, data hygiene and UI polish ([e768b52](https://github.com/bardesss/setvault/commit/e768b52f72714fc7fd3db66161f162e107d532f9))
* **quality:** treat an unknown stored cutoff as the best tier ([4c19e78](https://github.com/bardesss/setvault/commit/4c19e7890bdc4e3fec9a4170131a1fb16f02f112))
* **set_match:** "left unchecked" counts only fuzzy-only candidates; ordering tests ([1171c11](https://github.com/bardesss/setvault/commit/1171c11a00396a4d4907e8728b7eea64c9d20918))
* **settings:** tolerate an unknown stored upgrade schedule; test partial PUT ([5412545](https://github.com/bardesss/setvault/commit/541254507fd9f24f8b8d687dee3a2111b2d65e78))
* **sources:** discarded upgrade attempts aren't "in library"; approvals are monitor finds ([f1b4b7e](https://github.com/bardesss/setvault/commit/f1b4b7ece05a999cb141fd84fda46ddf24b0be62))
* **upgrade:** clamp shifted positions to the new duration, round half up ([120d3df](https://github.com/bardesss/setvault/commit/120d3dfd3df4698510f88f9be5799a0c64d885e2))
* **upgrade:** discard an upgrade-attempt rip the locked re-check refuses ([cf428f6](https://github.com/bardesss/setvault/commit/cf428f6ae5cfaa57cca7ef27ef17f0bc9905b877))
* **upgrade:** in-flight staleness by start time; enqueue-failure and rip-failed events ([00fd81b](https://github.com/bardesss/setvault/commit/00fd81b7594878c323e9d767257491528f876c22))
* **upgrade:** record the rejection even when the arrival row is already gone ([ca9c23f](https://github.com/bardesss/setvault/commit/ca9c23f407f3795aaad213bfa34bae053c52a09e))
* **upgrade:** swap repoints duplicates and resolved watch-folder files ([7a4e356](https://github.com/bardesss/setvault/commit/7a4e3569594d621f38bbae57d640f3a09d7bc336))
* **web:** bookmark toggle race behind the flaky e2e ([c5ae9f7](https://github.com/bardesss/setvault/commit/c5ae9f7158e55a61710901153b15df4f1513b1ec))
* **web:** bookmark toggle waits for its initial list; fixes flaky e2e ([8f1f602](https://github.com/bardesss/setvault/commit/8f1f60266dc87751767de205c6f5c0c368a6b361))
* **web:** format 7D dates in the UI language ([6e758c8](https://github.com/bardesss/setvault/commit/6e758c8dab7331d3bf97dc2efa0718915ee6bfb1))
* **web:** reactive Arrived date and time-zone independent date tests ([d6e1f87](https://github.com/bardesss/setvault/commit/d6e1f873cae16801f42d947cc7b64ca0d07b8d34))
* **web:** SetQuality uses the UI locale (en fallback), an i18n failure message and the error colour token ([d4e4c97](https://github.com/bardesss/setvault/commit/d4e4c973b08b5a2b37e577297aa6bd2e39df572d))


### Refactors

* **frontend:** replace $lib alias with #lib subpath imports ([2c6594d](https://github.com/bardesss/setvault/commit/2c6594dd389a65375dab9dff31320941e2efce48))
* **ready:** remove unused mark_ready_sync ([d158427](https://github.com/bardesss/setvault/commit/d15842720eaf64314d5e9488b71b96f0a5c4b6fa))
* **soundboard:** public strip_soundboard_terms; discoveries uses it ([d9b52f9](https://github.com/bardesss/setvault/commit/d9b52f989e0c73ce9cd342a7a15267d672d86820))


### Documentation

* **7d:** note the accepted limitations A1-A4 in code comments ([f1f497a](https://github.com/bardesss/setvault/commit/f1f497abeb4bd23aeea1309aecd88a285a985946))

## [0.18.0](https://github.com/bardesss/setvault/compare/v0.17.0...v0.18.0) (2026-10-19)


### Features

* **admin:** Quality and Wanted tabs ([a2a1e17](https://github.com/bardesss/setvault/commit/a2a1e17fd67bb0ef67a808f2a629ae3d45feace4))
* **duplicates:** show both copies' quality and what Discard keeps ([4ec973c](https://github.com/bardesss/setvault/commit/4ec973c59c806d333944fbad1f04808aaff3d7fb))
* **match:** duplicate detection uses fuzzy matching ([5d3896e](https://github.com/bardesss/setvault/commit/5d3896ed10afeb6ea1660b158dcde3f2a3f2f1ee))
* **match:** fuzzy chromaprint matcher with offset alignment ([9e1c0cf](https://github.com/bardesss/setvault/commit/9e1c0cf1366311a48a95ba13a6fc090436c20976))
* **notifications:** notify owners when a set is upgraded ([685ea7e](https://github.com/bardesss/setvault/commit/685ea7e5b0dfe300a83d10260526234156641252))
* **quality:** "Clean up duplicates" in the backfill box ([02a2593](https://github.com/bardesss/setvault/commit/02a25937a2da8abbaadec22c1d1fe588b40e8ef9))
* **quality:** 7D Bandcamp source, library duplicate cleanup, upgrade smoke ([3620f61](https://github.com/bardesss/setvault/commit/3620f6198b3f4c47a57baaa5b0addc97af9fab02))
* **quality:** 7D foundation — quality tiers, quality profile, fuzzy audio matching, backfill ([1670abe](https://github.com/bardesss/setvault/commit/1670abe1f72872e7a03e241af73257917ffbf6ab))
* **quality:** admin-triggered fingerprint + quality backfill ([45f295e](https://github.com/bardesss/setvault/commit/45f295e7fff7f251c9d7ca41e674858cb117cb7d))
* **quality:** backfill cleans up duplicates already in the library ([10d2b39](https://github.com/bardesss/setvault/commit/10d2b39ca088642178fbca71571924c0c7a42c49))
* **quality:** library-wide quality profile settings ([9ade553](https://github.com/bardesss/setvault/commit/9ade5537549f753e1aa88835e387572ef2852778))
* **quality:** measure set audio quality and tier it on probe ([858a49d](https://github.com/bardesss/setvault/commit/858a49de8dd437396fd427fdb90344f905f60cab))
* **rip:** prefer a lossless format when a source offers one ([1222d00](https://github.com/bardesss/setvault/commit/1222d0014e7998a2de4ba5c4e4a490e76682cac2))
* **sets:** hint when automatic upgrades are off library-wide ([fb9b2c4](https://github.com/bardesss/setvault/commit/fb9b2c417b2a2fede10260422e03d102a919fac8))
* **sets:** show quality, upgrade switch and history ([56260c6](https://github.com/bardesss/setvault/commit/56260c644d9682a9cdadd8e768060a4955dc7f16))
* **settings:** admins can set library maintenance notifications ([ff0f247](https://github.com/bardesss/setvault/commit/ff0f2474c1a8f44e35fcaf42857bc6c3ee4b8d72))
* **sources:** Bandcamp search source ([32f4939](https://github.com/bardesss/setvault/commit/32f4939d5d4c850ecfa52c0ec26592c7ea28addf))
* **sources:** expected quality on search candidates ([122cc6e](https://github.com/bardesss/setvault/commit/122cc6ebc4d3ecd51df6085a33c009976786860f))
* **upgrades:** 7D upgrade engine — automatic better-copy swaps, scheduled search, Quality/Wanted UI ([767d992](https://github.com/bardesss/setvault/commit/767d992f6b4827892496b25f91621f51d81dc669))
* **upgrades:** best-copy selection for monitors and search ([a7cd1e4](https://github.com/bardesss/setvault/commit/a7cd1e44ff7c76d694585e2eab608fff22619d90))
* **upgrades:** crash-safe set audio swap ([41b2edc](https://github.com/bardesss/setvault/commit/41b2edcae590542ac65906f743b516872720ad44))
* **upgrades:** scheduled upgrade search ([0dc8423](https://github.com/bardesss/setvault/commit/0dc8423653e5d45b4523e47f4af801cb61d4eb87))
* **upgrades:** upgrade history + rip upgrade targeting ([a646baf](https://github.com/bardesss/setvault/commit/a646baf92598ed8a366b791ab87171165b0cfec8))
* **upgrades:** upgrade or hold duplicates at ingest ([85ae992](https://github.com/bardesss/setvault/commit/85ae99240682f9d8b4f8a1c32ce7eba2c6e37891))


### Bug Fixes

* **admin:** plain-English Quality/Wanted pages, clear search error, order test ([0688dc7](https://github.com/bardesss/setvault/commit/0688dc77c204de81199b5a3f19275df4c90a4de7))
* **admin:** Wanted label, search guards and plain-English results ([b102cde](https://github.com/bardesss/setvault/commit/b102cde1d1436c61cba6968f065f078aa0af17ed))
* **bandcamp:** search tracks only ([092937d](https://github.com/bardesss/setvault/commit/092937da68ae5307e0f129a65b33b2fb7c2eba5d))
* **duplicates:** discard answers 409 when the original changed ([ca12766](https://github.com/bardesss/setvault/commit/ca1276643785bdc2645df22178479ebee7f434c2))
* **duplicates:** discarding a backfill match merges it into its original ([4fca61b](https://github.com/bardesss/setvault/commit/4fca61b183923b1487f3a276e62b3fbcd2198fe4))
* **fingerprint:** keep a better arrival when its original is in the recycle bin ([21daf70](https://github.com/bardesss/setvault/commit/21daf70332096c1e885ad498af602fe5f8ec42bc))
* **match:** exact legacy digest matches any candidate row ([e46e9a1](https://github.com/bardesss/setvault/commit/e46e9a184754c940b18987fa8869d9f61dc9c75f))
* **match:** keep the legacy exact hash for fingerprint rows without raw ([67618b6](https://github.com/bardesss/setvault/commit/67618b6effb5f44fe125bd6e829abd84dedb25b4))
* **match:** per-probe gate, worst-window guard, exact chromaprint hop ([37fd375](https://github.com/bardesss/setvault/commit/37fd37590c33e6d7e7edf8598a6a0d28d9fa2372))
* **notifications:** set_upgraded email is opt-in; guard missing owner ([51aa0cc](https://github.com/bardesss/setvault/commit/51aa0cc67ec42ef3ad463fe77a969c695c52dd59))
* **quality:** a purged fingerprint is no duplicate match ([cd92c55](https://github.com/bardesss/setvault/commit/cd92c55f6ed64d40dd6dacd2f1177e5291483ac8))
* **quality:** backfill honours a per-set deadline and holds no session during probes ([b39fbe0](https://github.com/bardesss/setvault/commit/b39fbe0d93595972002c1bd0412c732fd298b219))
* **quality:** backfill runs one bounded slice per job and re-enqueues itself ([560c2f6](https://github.com/bardesss/setvault/commit/560c2f68c7d03084a663dc6aa1263c51c940b1ae))
* **quality:** detect lossy low-pass cliff instead of comparing to full band ([6bfa193](https://github.com/bardesss/setvault/commit/6bfa1936fab4cb01355b25634e6a040796132347))
* **quality:** explain that tracklists move only to sets without one ([0aeedee](https://github.com/bardesss/setvault/commit/0aeedee6cdeba476dd0ee790c20ca37716235550))
* **quality:** legacy hash only pairs sets that can't be compared fuzzily ([ed1c976](https://github.com/bardesss/setvault/commit/ed1c976bac7ea6b2ccc1ce0b6e029fd7070afcfe))
* **quality:** log a warning when the fake-lossless check fails ([abb3b59](https://github.com/bardesss/setvault/commit/abb3b591f435ab620ed5745ee21c183539efec87))
* **quality:** merged positions stay inside the survivor's audio ([e55f92a](https://github.com/bardesss/setvault/commit/e55f92a2a5c0a5cb6b56a8d58454af0a9dd9a933))
* **quality:** one 180 s budget for the quality check, tighter fpcalc cap ([9e029eb](https://github.com/bardesss/setvault/commit/9e029ebdab264f4dd9403f9ff07022cdae7138e6))
* **quality:** recognise more lossless codecs (tta, tak, truehd, mlp, dsd_*, ...) ([c2b9a3a](https://github.com/bardesss/setvault/commit/c2b9a3a7267bcabdc58efb972ec3e45eba0bba38))
* **quality:** require absolute silence above cliff; add subprocess timeouts ([bd0fdf7](https://github.com/bardesss/setvault/commit/bd0fdf7445f73e0e8d54be295e82a4bdb9bcc9b2))
* **quality:** set history says when a merge kept the tracklist ([a07f16e](https://github.com/bardesss/setvault/commit/a07f16e2b13186ac1b68f82295462ba59f9895b9))
* **quality:** spell the ok tier "OK" in the label fallback ([64d3d18](https://github.com/bardesss/setvault/commit/64d3d18fce079b90ca7636132810222624f78c00))
* **quality:** starting the backfill doesn't recount duplicate pairs ([9227b47](https://github.com/bardesss/setvault/commit/9227b47b30ba640b340356856ec1a0d23417e0ff))
* **quality:** the backfill summary counts fill-phase errors ([00cc73c](https://github.com/bardesss/setvault/commit/00cc73c5f0f046581ca0cc7d0c07c934f465cd34))
* **quality:** the backfill summary reports cleanup errors ([cc63e64](https://github.com/bardesss/setvault/commit/cc63e646722de94eb7057fc13090c992121b94c1))
* **rips:** let discarded upgrade attempts not block later ingests ([eec2da2](https://github.com/bardesss/setvault/commit/eec2da200e65378f5f0bc6a69eddc457f5ef068f))
* **sets:** key upgrade history by event id ([5c15e92](https://github.com/bardesss/setvault/commit/5c15e92e51ed4bc88540669b62d2726d78f12d49))
* **sources:** Bandcamp candidates have an unknown expected tier ([a3c47ad](https://github.com/bardesss/setvault/commit/a3c47ad6420fee59ad02940f81319a93eeb6d1fc))
* **sources:** Bandcamp search via the public JSON endpoint ([d69b2e6](https://github.com/bardesss/setvault/commit/d69b2e670712a5b3a7fb8ff38e7e71cef4f8fe01))
* **upgrades:** don't stamp a set when every source errored ([ef613a2](https://github.com/bardesss/setvault/commit/ef613a2605b836f8aa2a4a23e3507e49ac61ff5b))
* **upgrades:** failed upgrade rips count as tried ([002b30e](https://github.com/bardesss/setvault/commit/002b30eb6256127cb145d3e30c76da9774984cb0))
* **upgrades:** judge an upgrade attempt against its target only ([646739d](https://github.com/bardesss/setvault/commit/646739dbf58e4b11b2023baae4a7a21bfd57534b))
* **upgrades:** lock rows for the swap; never hard-delete swapped sets ([9b352a8](https://github.com/bardesss/setvault/commit/9b352a8d1ee6dfff699bf6c860cf098180c2c145))
* **upgrades:** never delete files another set uses; repoint rip; gate webhooks ([3fc7399](https://github.com/bardesss/setvault/commit/3fc73995ec6f7b815ce0b6f13000bbe4d030a642))
* **upgrades:** re-check upgrade under lock; owner rule; search-now switch ([d075102](https://github.com/bardesss/setvault/commit/d075102cb1ab05af34858acb7029e4f781c9e887))
* **upgrades:** record a failed upgrade-attempt rip as a rejected candidate ([a28712c](https://github.com/bardesss/setvault/commit/a28712ca25169e1f35e6c06a116194d76e2fb547))
* **upgrades:** record monitor and source-search triggers on rips ([03fc9b0](https://github.com/bardesss/setvault/commit/03fc9b0d7c939bd1f9fa9138811f085348e480ab))
* **upgrades:** restored replaced copy lands on the Duplicates page ([28a8074](https://github.com/bardesss/setvault/commit/28a807483f011856690ae1225aa75380b706539b))
* **upgrades:** run upgrade work on a low-priority queue with an in-flight cap ([3f0df4d](https://github.com/bardesss/setvault/commit/3f0df4da417d1f63ccc0dc706904bb34f2f32a17))
* **upgrades:** run-now timeout, duplicate picks, probe failures, batch budget ([ea74fb8](https://github.com/bardesss/setvault/commit/ea74fb8d1c6c0d41fd57787f7efaf06206bd284e))
* **upgrades:** shifting play positions keeps their updated_at ([192aaf2](https://github.com/bardesss/setvault/commit/192aaf2e9d219f4751d82450716f74f38117e5ba))
* **wanted:** search-now refuses sets that aren't fingerprinted yet ([9a94c6b](https://github.com/bardesss/setvault/commit/9a94c6b832aebed6e6ae613dcb5b90ec621fec9d))
* **wanted:** show a refused search on that set's row ([91370f9](https://github.com/bardesss/setvault/commit/91370f9105c6856be58fd171ced4e9659ed04b99))
* **worker:** actually run scheduled jobs (rq-scheduler loop) + reset recycle-bin grace ([252cd46](https://github.com/bardesss/setvault/commit/252cd4679f842b25f0699aa3e96ff3d49137353b))
* **worker:** run rq-scheduler so periodic jobs actually fire ([2df1157](https://github.com/bardesss/setvault/commit/2df11572a7d8f7014d8fd198e6b5ca5ad5514e31))


### Performance

* **match:** fetch candidate fingerprints lazily and cap compares at 200 ([824689f](https://github.com/bardesss/setvault/commit/824689fa0bd2e1ee5dacdf51047f6bf16d10061d))
* **upgrades:** index rip_jobs.upgrade_target_set_id ([2b8044d](https://github.com/bardesss/setvault/commit/2b8044d4e129557890cf4d3a9b45b69e6c30b929))


### Refactors

* **quality:** make is_better's lossless flags required keyword-only ([67e94ab](https://github.com/bardesss/setvault/commit/67e94aba0c7112666ea709cbae602ab72d0deaf2))
* **quality:** move apply_quality to services/audio_quality ([95bd695](https://github.com/bardesss/setvault/commit/95bd695dc08a7bd478ecf1d0369be8c31cf73eb5))


### Documentation

* **models:** say what duplicate_kept_at is used for ([c3cc481](https://github.com/bardesss/setvault/commit/c3cc481116555943c36d4df87a7aa6b5aad3da93))

## [0.17.0](https://github.com/bardesss/setvault/compare/v0.16.0...v0.17.0) (2026-10-18)


### Features

* **admin:** hold fingerprint duplicates for review instead of publishing ([5d45346](https://github.com/bardesss/setvault/commit/5d4534620c787401c0263474589d89f6d3c33751))


### Bug Fixes

* **ingest:** bind tus uploads to their owner; enforce rip byte cap ([be3d594](https://github.com/bardesss/setvault/commit/be3d594ed849338d37ca5f5e70c900380f43cc53))
* **ingest:** harden tusd hook, rip submit ordering, yt-dlp guards, tus spool ([785e99b](https://github.com/bardesss/setvault/commit/785e99bb0c40d6d536c3a4b74fc587780fb75716))
* **ingest:** harden tusd hook, rip submit ordering, yt-dlp guards, tus spool ([3f66e5f](https://github.com/bardesss/setvault/commit/3f66e5f4ec2233c343ae744a9fbfc6ca7de0404b))
* **ingest:** job timeouts, dedup crash, watch-folder races; hold duplicates for review ([f9b7144](https://github.com/bardesss/setvault/commit/f9b714449b82e5188d844b14cb28068fa6d8e3c4))
* **ingest:** job timeouts, fingerprint dedup crash, watch-folder races ([ffb9549](https://github.com/bardesss/setvault/commit/ffb95491da500d08e1bb3406897db894f73976c0))
* **ingest:** watcher catch-up scan, failed-rip cleanup, poll dedup, enabled roots ([f6c8c02](https://github.com/bardesss/setvault/commit/f6c8c02bde7f88ccc86b7b410610a1e18464b0e2))
* **ingest:** watcher catch-up scan, failed-rip cleanup, poll dedup, enabled roots ([d9fbd89](https://github.com/bardesss/setvault/commit/d9fbd89f71a14f2b373c3f89520db0eb0a409df3))
* **uploads:** judge tus completeness by spool file size, not .info Offset ([8301d0c](https://github.com/bardesss/setvault/commit/8301d0ced0128f5ac423a1531a7e563ec53bc7eb))

## [0.16.0](https://github.com/bardesss/setvault/compare/v0.15.2...v0.16.0) (2026-10-17)


### Features

* **admin:** backfill normalized_lufs for sets stuck at the bogus -70.0 ([ed50d44](https://github.com/bardesss/setvault/commit/ed50d44e0971a41aa94da8807c75a13beb1db2eb))


### Bug Fixes

* fingerprint URL rips, attribute watch-folder sets to their creator ([b885466](https://github.com/bardesss/setvault/commit/b885466b4d6d7409eaf136e7432f322ce2edc542))
* harden ingest paths (smoke all ingest paths, LUFS backfill, engine-per-job leak) ([7f17944](https://github.com/bardesss/setvault/commit/7f17944284927147280230e2315640de28d0bf9b))
* **jobs:** dispose the pooled engine at the end of every sync RQ entrypoint ([20c02d5](https://github.com/bardesss/setvault/commit/20c02d50bde2b4cbf8858e5af929d6865f39e27f))
* surface failed discovery rips, briefly cache provider errors; pre-bundle dev deps ([c903c73](https://github.com/bardesss/setvault/commit/c903c73e95b38d2bc6e8363bc41ad15b82797239))
* surface failed discovery rips; log and briefly cache provider errors ([af3c2b9](https://github.com/bardesss/setvault/commit/af3c2b92a1a18d783e06948b40ae2ab8dcb7931a))
* **url-rip:** fingerprint rips so they get chromaprint dedup ([368808f](https://github.com/bardesss/setvault/commit/368808f67770b740df134b248475dfe6bc5d41ad))
* **watch-folder:** attribute ingested sets to the folder's creator ([5e4ac4b](https://github.com/bardesss/setvault/commit/5e4ac4b3b8258a9e5687380025654e89fbbcfb67))

## [0.15.2](https://github.com/bardesss/setvault/compare/v0.15.1...v0.15.2) (2026-10-15)


### Bug Fixes

* **pipeline:** fpcalc exit 3, stuck failed sets, LUFS parse; run audio tests in CI ([66d20e1](https://github.com/bardesss/setvault/commit/66d20e1e36b092b3c7d631346a0f5e9aff430c60))
* **pipeline:** uploads no longer hang on fpcalc exit 3; real LUFS values ([8b1e38d](https://github.com/bardesss/setvault/commit/8b1e38d36d30cc04c30e57e6807cc42fcf22e494))

## [0.15.1](https://github.com/Bardesss/setvault/compare/v0.15.0...v0.15.1) (2026-06-18)


### Bug Fixes

* **transcode:** force opus muxer so .opus.tmp output works ([f0b9cbb](https://github.com/Bardesss/setvault/commit/f0b9cbb4df307da9bf462a49308253766fb475c4))
* **transcode:** force opus muxer so .opus.tmp output works ([aab9655](https://github.com/Bardesss/setvault/commit/aab96557633a14b425c91311b16573aad30ae54e))

## [0.15.0](https://github.com/Bardesss/setvault/compare/v0.14.1...v0.15.0) (2026-06-18)


### Features

* catalog curation — merge/dedup/delete + artist enrich (D2) ([a88df20](https://github.com/Bardesss/setvault/commit/a88df2092ed57218a9cc8f45ca48ea94c73d208f))
* **catalog:** admin catalog API client ([e7a681e](https://github.com/Bardesss/setvault/commit/e7a681e570532123dfb0cfa0cbde7edc46b9b51a))
* **catalog:** admin Catalog tab (browse, dedup, merge, delete) ([22967b1](https://github.com/Bardesss/setvault/commit/22967b1f906bc41a39648bfe50775fe76c18448c))
* **catalog:** admin list + duplicate-suggestions API ([b6136c7](https://github.com/Bardesss/setvault/commit/b6136c7fede8ce13490b4ff5d6a4295c1cc969be))
* **catalog:** artist enrich button + admin merge e2e ([a20979c](https://github.com/Bardesss/setvault/commit/a20979c7076d52f2e077fe3d08621db659467eda))
* **catalog:** artist enrichment service (locking-aware) ([b3654de](https://github.com/Bardesss/setvault/commit/b3654de7df0bb8086f33ecc745f8b0936d39c9f6))
* **catalog:** duplicate-cluster detection by normalized name ([2706cb3](https://github.com/Bardesss/setvault/commit/2706cb332f70c4ffc91948378ba803c0466fab76))
* **catalog:** hide tombstoned entities from reads ([90bf192](https://github.com/Bardesss/setvault/commit/90bf192e1b6a1661ba2cebdc652b7f7beefb3b00))
* **catalog:** list merged entities + Unmerge action in admin tab ([c0ff787](https://github.com/Bardesss/setvault/commit/c0ff787dec3e64f141622fc3871d696fd4c28169))
* **catalog:** merge/unmerge/delete + artist enrich endpoints ([910a3cb](https://github.com/Bardesss/setvault/commit/910a3cb28eab3436372d37de7c0ceefe6af48777))
* **catalog:** reversible entity merge service ([f06cecf](https://github.com/Bardesss/setvault/commit/f06cecfbebc6fa02ba11d355cdfa68e5cd5d7056))
* **catalog:** reversible-merge tombstone columns ([ccda3f0](https://github.com/Bardesss/setvault/commit/ccda3f0a9e9bb2142bf9ed841b0baded48679e1a))
* **catalog:** unmerge replays the merge manifest ([3b42d6e](https://github.com/Bardesss/setvault/commit/3b42d6e5db5397d0a801978f455797dabd83d34e))


### Bug Fixes

* **catalog:** merge raises ValueError on unknown kind ([f4a3dc6](https://github.com/Bardesss/setvault/commit/f4a3dc665a9559b4a0a21b2125dd2df7d7a1d1bc))
* **catalog:** surface artist enrich failures to the user ([44bfc2a](https://github.com/Bardesss/setvault/commit/44bfc2ac86be904cd289ccee8500ab1aeefa08e8))
* **catalog:** unmerge compares artist_id as UUID not str ([41ee9ef](https://github.com/Bardesss/setvault/commit/41ee9efd748ad240453c50140d0568885c76e8b7))
* **catalog:** unmerge round-trip tests for venue + dropped-join; 400 on bad survivor_id ([87a5842](https://github.com/Bardesss/setvault/commit/87a58426a060b444b30fda8046cd9ae9f6e44c12))

## [0.14.1](https://github.com/Bardesss/setvault/compare/v0.14.0...v0.14.1) (2026-06-17)


### Bug Fixes

* **url-rip:** debuggable failures + waveform handles AAC; retry replaces row ([9bb9493](https://github.com/Bardesss/setvault/commit/9bb9493ce4bda79b07d0716c1bcc7684eba5ab56))
* **url-rip:** debuggable failures + waveform handles AAC; retry replaces row ([c3f46cd](https://github.com/Bardesss/setvault/commit/c3f46cd49c3fe56e3b5056130f01d55fcf26ac16))

## [0.14.0](https://github.com/Bardesss/setvault/compare/v0.13.0...v0.14.0) (2026-06-17)


### Features

* catalog entity pages + edit (D1) ([f1ba73e](https://github.com/Bardesss/setvault/commit/f1ba73e04d353b2acb0947e29e65ec0a0b980920))
* **catalog:** artist detail page with edit ([ea17aae](https://github.com/Bardesss/setvault/commit/ea17aae694d9a3beb98b93a3d21b02508fd6ff86))
* **catalog:** EntitySetsGrid component ([d919f24](https://github.com/Bardesss/setvault/commit/d919f2403809c3fa88d654c8ca1e69d2a72ee580))
* **catalog:** frontend catalog API client ([441470e](https://github.com/Bardesss/setvault/commit/441470e8a633b511cd55d47cd3225f37521da795))
* **catalog:** GET /{kind}/{slug}/sets endpoint ([03c6420](https://github.com/Bardesss/setvault/commit/03c64204faeb54a55fd18cc46064478d63513c09))
* **catalog:** link entity names to detail pages + i18n ([3138b89](https://github.com/Bardesss/setvault/commit/3138b89fc612aab8ba7dfcfcdb77ba7b34bf49e2))
* **catalog:** list_sets_for_entity service ([4ce7ec1](https://github.com/Bardesss/setvault/commit/4ce7ec14f884c640c617d7959eb40db390616315))
* **catalog:** member edit (PATCH) for entities ([af6da1d](https://github.com/Bardesss/setvault/commit/af6da1dd3c49eb1aea61a538ed83462fff31524a))
* **catalog:** partial-update patch schemas ([de83b8c](https://github.com/Bardesss/setvault/commit/de83b8c4c51f386b93dddd8afb66f5061cb68ed6))
* **catalog:** venue, party, series detail pages with edit ([963db2c](https://github.com/Bardesss/setvault/commit/963db2c861f78a64d5c067888e1dda02ae60f715))


### Bug Fixes

* **catalog:** robust edit endpoints (409/422 on bad input) + audit-log edits ([7400a16](https://github.com/Bardesss/setvault/commit/7400a16293d3d7302c73da75cad76772bef7a9b0))
* **catalog:** surface edit-save errors on entity pages ([454a0bc](https://github.com/Bardesss/setvault/commit/454a0bc7709365b5bb5314ff2362900cc3e0103a))

## [0.13.0](https://github.com/Bardesss/setvault/compare/v0.12.0...v0.13.0) (2026-06-17)


### Features

* **auth:** optional single-user auto-login ([149593f](https://github.com/Bardesss/setvault/commit/149593fc497c3ac5a73c32d7c04c8db990014ff7))
* **downloads:** clear individual or finished downloads ([addaa18](https://github.com/Bardesss/setvault/commit/addaa184701aa6eee11a8f870954b09370b3e6d5))
* login redirect, clear-downloads, and single-user auto-login ([8d48af7](https://github.com/Bardesss/setvault/commit/8d48af7bdc7a71f86f183463452409108e52e9e8))


### Bug Fixes

* **frontend:** redirect logged-out users to /login ([8a19922](https://github.com/Bardesss/setvault/commit/8a199220d1f6b55c28cc65ed0b60c79666ee87ba))

## [0.12.0](https://github.com/Bardesss/setvault/compare/v0.11.4...v0.12.0) (2026-06-17)


### Features

* **frontend:** add a downloads page with live progress and retry ([315289c](https://github.com/Bardesss/setvault/commit/315289cf4e2c64b98ee91ede3b67c69a56a84d0c))
* **ingest:** auto-provision default media root from mounted folder ([7886c6f](https://github.com/Bardesss/setvault/commit/7886c6f967758da83e74c315d0450f80d5568c53))
* mounted livesets folder, downloads page, and thumbnail proxy ([a5e1eec](https://github.com/Bardesss/setvault/commit/a5e1eeca25ba54bd6c1fca6e8f05ad5e45e03190))


### Bug Fixes

* **search:** proxy external thumbnails so the CSP can render them ([4d6f63e](https://github.com/Bardesss/setvault/commit/4d6f63e139d077d39a8411b2a06781f63c3d4f0a))

## [0.11.4](https://github.com/Bardesss/setvault/compare/v0.11.3...v0.11.4) (2026-06-17)


### Bug Fixes

* **pwa:** don't bleed user-scoped cache across sessions ([76dfe2d](https://github.com/Bardesss/setvault/commit/76dfe2d9dc647b4ba0b35099ccfde941339bb2ea))
* **pwa:** isolate user-scoped cache across sessions ([d5d9afe](https://github.com/Bardesss/setvault/commit/d5d9afe30b9f62a6d38f0c8d3832a6f9dabba0f3))

## [0.11.3](https://github.com/Bardesss/setvault/compare/v0.11.2...v0.11.3) (2026-06-17)


### Bug Fixes

* **frontend:** convert server loads to universal loads for static SPA ([bd80639](https://github.com/Bardesss/setvault/commit/bd80639e676de92aa50e9ffe0f8d3490a4f12a09))
* **frontend:** convert server loads to universal loads for static SPA ([a0a0cb7](https://github.com/Bardesss/setvault/commit/a0a0cb77af6a2c64c08ff6f72cd84f2bb7370c40))
* **pwa:** cache /api GETs network-first so SPA pages work offline ([9788f52](https://github.com/Bardesss/setvault/commit/9788f5283cb8b29e30fb8ee3e8b77eaa7c1c1f11))

## [0.11.2](https://github.com/Bardesss/setvault/compare/v0.11.1...v0.11.2) (2026-06-16)


### Bug Fixes

* **web:** hash SvelteKit inline bootstrap so strict CSP allows hydration ([7c2ab3e](https://github.com/Bardesss/setvault/commit/7c2ab3e4bfe2cd60bc7a618528a3949ba52858df))
* **web:** hash SvelteKit inline bootstrap so strict CSP allows hydration ([dcee0f8](https://github.com/Bardesss/setvault/commit/dcee0f8a8d5b24f4880c893e95b6ae3a68ae5261))


### Documentation

* **readme:** note that HTML-rewriting proxies break the hashed CSP ([fcc49c7](https://github.com/Bardesss/setvault/commit/fcc49c7e39f36ecc904e83161920560c72dcf989))

## [0.11.1](https://github.com/Bardesss/setvault/compare/v0.11.0...v0.11.1) (2026-06-16)


### Documentation

* **readme:** add clear step-by-step deploy walkthrough ([89f4b0a](https://github.com/Bardesss/setvault/commit/89f4b0a83dd7efda17b07ef8446c810aefd74dfe))
* **readme:** add Docker Compose quick-start steps ([864ed21](https://github.com/Bardesss/setvault/commit/864ed21659a5597d5b978f06910d4da7da59d4b4))
* **readme:** step-by-step deploy guide + Docker Compose quick-start ([4065675](https://github.com/Bardesss/setvault/commit/4065675a5382f8b453b311d74c0848821d295f1d))

## [0.11.0](https://github.com/Bardesss/setvault/compare/v0.10.0...v0.11.0) (2026-06-16)


### Features

* **7c:** admin settings — monitors-allow-all + poll interval ([be1ec14](https://github.com/Bardesss/setvault/commit/be1ec14dcb6ef39213df107ef47d54b0da453176))
* **7c:** deterministic confidence scoring for discoveries ([e0aacd3](https://github.com/Bardesss/setvault/commit/e0aacd355d57017ffe30de8b00dab6391a6f36fa))
* **7c:** Discoveries inbox page + bell routing for discovery kind ([7044616](https://github.com/Bardesss/setvault/commit/704461620b070adf006417726b38f3a9f3e28191))
* **7c:** discovery service — dedup, auto-ingest gate, notify ([b1b8282](https://github.com/Bardesss/setvault/commit/b1b828245e3671645ec87801a87044e37e33614a))
* **7c:** expose + update per-source rate limits via Sources API ([19a1cb8](https://github.com/Bardesss/setvault/commit/19a1cb8071609a56be191a693d74e22cf8296385))
* **7c:** frontend API clients for monitors + source rate limits ([38b77f6](https://github.com/Bardesss/setvault/commit/38b77f67a2f43b35e180440096c2a23d5ab6b557))
* **7c:** i18n keys for monitors + discoveries ([ed3b354](https://github.com/Bardesss/setvault/commit/ed3b354a6ea5c5a8c53252287915a269b4b79712))
* **7c:** migration — monitor tables, source rate limits, config ([65b5f89](https://github.com/Bardesss/setvault/commit/65b5f89f49ed7cd124efcef90d17bfce5b3a88f3))
* **7c:** monitor + discovery Pydantic schemas ([10da73e](https://github.com/Bardesss/setvault/commit/10da73e95eb0136404bb55e1936b7fd5406660f4))
* **7c:** Monitor + MonitorDiscovery models + test cleanup fixtures ([da370ee](https://github.com/Bardesss/setvault/commit/da370ee68463a837b99fae2f55ec6bb30a59f773))
* **7c:** monitor service — CRUD + due-selection ([2c792a1](https://github.com/Bardesss/setvault/commit/2c792a130a270f2d7406f842ccb5f27fd32517f9))
* **7c:** monitor_dispatch scheduled job + worker registration ([5f8d255](https://github.com/Bardesss/setvault/commit/5f8d255c7506213a9990b690c1f2756e1106b29f))
* **7c:** monitor_poll RQ job ([41d891c](https://github.com/Bardesss/setvault/commit/41d891ca9f03a1bfe10b4d9a41399a9528c89040))
* **7c:** monitored entities + discoveries inbox + per-source rate limits ([2f6a611](https://github.com/Bardesss/setvault/commit/2f6a61109d859787df948c31b1a1660f9b58f723))
* **7c:** Monitors admin tab ([82cdf82](https://github.com/Bardesss/setvault/commit/82cdf82cdbb625c0b32ec8e5792729c586493af9))
* **7c:** monitors CRUD + discoveries inbox API ([f25bde0](https://github.com/Bardesss/setvault/commit/f25bde0c0a8780da8195a131d68462f07b094e40))
* **7c:** per-source rate-limit + monitor-settings columns ([33e9fa7](https://github.com/Bardesss/setvault/commit/33e9fa73ab077a0e939d74f8088193f3157db96f))
* **7c:** per-source Redis rate limiter wired into search ([8acdcec](https://github.com/Bardesss/setvault/commit/8acdceca2973eb08a13243fa6ffbb8ae661b3d9d))
* **7c:** source rate-limit inputs + monitor settings UI ([086ecd8](https://github.com/Bardesss/setvault/commit/086ecd88a06ffc5286870963648cae7d395ba3ec))


### Bug Fixes

* **7c:** owner-scope monitors + discoveries to close IDOR ([aa3d037](https://github.com/Bardesss/setvault/commit/aa3d0376bac200e46f68d47260e212f26a6375a4))


### Refactors

* **7c:** address Task 11 review — gate via Depends, harden rip enqueue ([8beab8f](https://github.com/Bardesss/setvault/commit/8beab8fd6f55466125ed00ca85a11ff258ce2a24))
* **7c:** address Task 5 review — drop redundant _run param, unused import ([8b9ad08](https://github.com/Bardesss/setvault/commit/8b9ad083eda6ea9a6c94b4eece37c48482ea99f4))
* **7c:** log swallowed auto-ingest failures in discovery service ([bd4bd92](https://github.com/Bardesss/setvault/commit/bd4bd923dcca14e54d80c1b3c2cdbc8e8c363ca4))


### Documentation

* **readme:** simplify — trim verbose prose, collapse roadmap ([21266e5](https://github.com/Bardesss/setvault/commit/21266e5c7aaa1431862d0ceb6ac35ac8f93e3230))
* **readme:** simplify — trim verbose prose, collapse roadmap table ([5cb1ff4](https://github.com/Bardesss/setvault/commit/5cb1ff4d5dc674a2b38debc44fcce4e2a000e923))

## [0.10.0](https://github.com/Bardesss/setvault/compare/v0.9.0...v0.10.0) (2026-06-15)


### Features

* **deploy:** auto-generate SECRET_KEY + default BASE_URL in bundled mode ([f83d430](https://github.com/Bardesss/setvault/commit/f83d43064b40364f1dec9125aa0d3a190c1e5234))
* **deploy:** require BASE_URL only in external mode; SECRET_KEY now always set ([1cec7d7](https://github.com/Bardesss/setvault/commit/1cec7d731f1f9f67fa2dcc8b9854b25a9dc90e1b))
* **setup:** first-run admin wizard endpoint (status + self-locking create + auto-login) ([6957de0](https://github.com/Bardesss/setvault/commit/6957de050d4d407fb367c7a75434a1b9afe841f9))
* **setup:** first-run admin wizard page + redirect gate ([37e02b6](https://github.com/Bardesss/setvault/commit/37e02b6550864f99b1aa1a98aecc261fd50ff08a))


### Bug Fixes

* **deploy:** make AIO compose secrets optional so bundled mode is truly zero-config ([1538770](https://github.com/Bardesss/setvault/commit/15387702ec2c9ca78a7a1c26350f03a17c4c2964))
* **deploy:** restrict perms on persisted + tmpfs secret files (0600) ([95d063e](https://github.com/Bardesss/setvault/commit/95d063ec1b8728674a6ccab1c67e1ced281802e4))


### Performance

* **setup:** skip first-run gate on public routes; trim wizard email ([082cb9a](https://github.com/Bardesss/setvault/commit/082cb9a07839062daae1c8d8202fc27d4037e89d))


### Documentation

* **deploy:** wizard-first first-run; bundled mode needs zero env vars ([fb42daf](https://github.com/Bardesss/setvault/commit/fb42daf87f8a2994f093212eed63d096ab9e694f))

## [0.9.0](https://github.com/Bardesss/setvault/compare/v0.8.2...v0.9.0) (2026-06-15)


### Features

* **7b:** /search shows merged multi-source results with source chips + unavailable notice ([2c10fc8](https://github.com/Bardesss/setvault/commit/2c10fc8e98fe8988671e1659c3d534350814284f))
* **7b:** frontend client searches all sources (+partial-unavailable i18n) ([4618050](https://github.com/Bardesss/setvault/commit/4618050b025057251eba309c14206cf8b8aa5e48))
* **7b:** ingest-sources API searches all sources + cross-source in-library flag ([61340b6](https://github.com/Bardesss/setvault/commit/61340b6dd25595078168dbc0ec36be10e5ea65d4))
* **7b:** Internet Archive source + register all four sources ([c1e4306](https://github.com/Bardesss/setvault/commit/c1e4306fb8067a5f0846430beea484156b9ef186))
* **7b:** Mixcloud ingest source via public search API ([2baa974](https://github.com/Bardesss/setvault/commit/2baa9749820d562197221e3f42ca8dd87d537497))
* **7b:** search_all_sources — concurrent multi-source search + shared state helpers ([c4119c8](https://github.com/Bardesss/setvault/commit/c4119c803a589916f5659cf97b74d9fad98f1199))
* **7b:** SoundCloud ingest source via yt-dlp scsearch ([f045e82](https://github.com/Bardesss/setvault/commit/f045e82c619d5afb65f6363a19e347b7b86a5fea))
* **phase-7b:** more sources + multi-source search ([63656e9](https://github.com/Bardesss/setvault/commit/63656e90efb6b546ea66bbd258c49d6376cb757a))


### Bug Fixes

* **7b:** narrow search_all exception handling — propagate bugs/cancellation, bind source once ([bc3a8f3](https://github.com/Bardesss/setvault/commit/bc3a8f3ee1e6696239ebe14b77e4651524da1aae))


### Performance

* **7b:** scope in-library query to candidate keys (avoid full rip_jobs scan) ([ae2ea53](https://github.com/Bardesss/setvault/commit/ae2ea538b828446b0d9a39b1089c405da4b3588f))


### Refactors

* **7b:** extract _YtDlpSearchSource base from youtube source ([e10f6e7](https://github.com/Bardesss/setvault/commit/e10f6e734a3e9853d3e0307c6632ba4db97a4337))


### Documentation

* **landing:** 7B multi-source search shipped (v0.9.0); monitoring still roadmap (7C) ([51cd631](https://github.com/Bardesss/setvault/commit/51cd631dad6e62cd7777f827a3e47809bcd4b8bf))
* **readme:** bump what's-in-the-box to v0.9.0; 7B this release, 7A merged ([5e0e3f9](https://github.com/Bardesss/setvault/commit/5e0e3f96b6cd1e3f8a642c3b8300ee1cae42c539))

## [0.8.2](https://github.com/Bardesss/setvault/compare/v0.8.1...v0.8.2) (2026-06-15)


### Bug Fixes

* **security:** fail closed when BASE_URL scheme is unknown ([ef3975c](https://github.com/Bardesss/setvault/commit/ef3975c3aa665d2f3defe0be20eda96968e4f900))


### Refactors

* **security:** single canonical origin for emitted URLs ([c3aaea6](https://github.com/Bardesss/setvault/commit/c3aaea6392a28061015323cddfaa229993878328))
* **security:** single canonical origin for emitted URLs (BASE_URL) ([53f0b3f](https://github.com/Bardesss/setvault/commit/53f0b3f38f133a7fe4656282d38f1e542429d10e))

## [0.8.1](https://github.com/Bardesss/setvault/compare/v0.8.0...v0.8.1) (2026-06-15)


### Documentation

* **readme:** reframe HTTPS requirement as three deployment modes ([2add694](https://github.com/Bardesss/setvault/commit/2add694733b925156d15bc1def0dd35e190f0686))
* reframe HTTPS requirement as three deployment modes ([a7190a9](https://github.com/Bardesss/setvault/commit/a7190a9c77857cff471efd5c1e8e1045a88951f6))

## [0.8.0](https://github.com/Bardesss/setvault/compare/v0.7.0...v0.8.0) (2026-06-15)


### Features

* **7a:** /search Sources mode — YouTube search + Ingest ([bd4e144](https://github.com/Bardesss/setvault/commit/bd4e144ea893e18edd769eff7e2ad9fd748afcba))
* **7a:** admin Sources tab (enable/disable + state) ([5abbf5a](https://github.com/Bardesss/setvault/commit/5abbf5a98814463b57d629f076b6bc8a4b7b33e6))
* **7a:** frontend ingest-sources api client + i18n keys ([42cf3d0](https://github.com/Bardesss/setvault/commit/42cf3d0c181400a5a51be4d17fec1b92a619dc9c))
* **7a:** ingest_source_state model + migration ([0bdff69](https://github.com/Bardesss/setvault/commit/0bdff6900842b75c36a765a941382e7c6abe0f8c))
* **7a:** ingest_sources package — IngestSource protocol + Candidate ([bcb7da2](https://github.com/Bardesss/setvault/commit/bcb7da2320cc48bfafb4fec62079fba3a5edfb5a))
* **7a:** ingest-source service — search + auto-disable state machine ([83c7254](https://github.com/Bardesss/setvault/commit/83c7254f36724f7c280cea3c7f7b40a5ebabf9c4))
* **7a:** ingest-sources API — search (+in-library flag) + admin toggle ([69e9af8](https://github.com/Bardesss/setvault/commit/69e9af87be36f31de14f9fc326879faa7fff4a11))
* **7a:** YouTube ingest source via yt-dlp ytsearch + registry ([11fdf34](https://github.com/Bardesss/setvault/commit/11fdf3418203c9ec3e23a23f6f8b40745e58b81a))
* **phase-7a:** ingest sources — IngestSource protocol + YouTube search + Sources tab ([b868007](https://github.com/Bardesss/setvault/commit/b8680070549fdaa7cb667c0ffa450c4a1d62a402))


### Bug Fixes

* **7a:** COPY packages/ingest_sources in bundled Dockerfile ([e9b844b](https://github.com/Bardesss/setvault/commit/e9b844b5b36bd271a20060e7af45c888306088de))
* **7a:** distinct search-submit aria-label + i18n ingest-failed string ([8b1382c](https://github.com/Bardesss/setvault/commit/8b1382c47461ad460411a55cce445c769e934a8e))
* **7a:** seed source states before search so first run works ([f6c1aa4](https://github.com/Bardesss/setvault/commit/f6c1aa42d9c56d7e01933bf1126528e7b40dc6c9))


### Refactors

* **7a:** log+narrow 502 path, dedupe state-out helper, bound search limit, real test status ([b453cc6](https://github.com/Bardesss/setvault/commit/b453cc6a0ed96592f7df0bb31a5e9a87ea8ab12f))
* **7a:** registry — bind single YouTubeSource instance ([3d76644](https://github.com/Bardesss/setvault/commit/3d76644901f279a64e89f33446eb342a997d223f))


### Documentation

* **readme:** mark bundled+hardening merged; 7A ingest-sources this release (v0.8.0) ([c1d79e0](https://github.com/Bardesss/setvault/commit/c1d79e01a1e249d97f69b629ad726c49d72b1d93))

## [0.7.0](https://github.com/Bardesss/setvault/compare/v0.6.0...v0.7.0) (2026-06-08)


### Features

* **admin:** create-admin CLI for safe first-admin bootstrap (B1) ([c8d508c](https://github.com/Bardesss/setvault/commit/c8d508ce13852736b3d368f3258109853359a085))
* **ops:** restore CLI + backup memory hardening + backup tests (B3) ([466a472](https://github.com/Bardesss/setvault/commit/466a472ac21ef60db8eb1c9eca4a3099abd4d846))


### Bug Fixes

* **ops:** pg_dump --clean --if-exists so restore works into a populated DB ([7c0684c](https://github.com/Bardesss/setvault/commit/7c0684c25ec31534bfe6cb9debcb85dd49a531e9))
* pre-launch hardening — security, admin bootstrap, restore, reachability ([b9ba404](https://github.com/Bardesss/setvault/commit/b9ba404bd7f0b90f68ad2c347f5a23121061119f))
* **security:** effective validation gate, activity scoping, secret hygiene ([28f5d50](https://github.com/Bardesss/setvault/commit/28f5d508776305a949e6d3b018c1cdfb9827d5ee))
* **security:** SECRET_KEY strength gate + cookie/CSRF/redaction hardening ([fa2ea34](https://github.com/Bardesss/setvault/commit/fa2ea34af8d3929c2b863bf90f2f82cc01926faf))
* **ui:** reachable /sets/new + mount NotificationBell; drop dead RoadmapTag ([b6538ce](https://github.com/Bardesss/setvault/commit/b6538ce16b9b86ac3b2273c2822a4336f535fde8))

## [0.6.0](https://github.com/Bardesss/setvault/compare/v0.5.0...v0.6.0) (2026-06-08)


> **⚠️ Upgrade caveat — Postgres 16 → 18.** The bundled stack now pins
> **Postgres 18** (earlier builds used Postgres 16). A PG-16 data directory is
> not binary-compatible with PG 18 and Postgres will refuse to start on it. If
> you ran an earlier SetVault on Postgres 16, **dump on 16 and restore into 18**
> via the admin backup endpoint + the new `python -m setvault_web.restore` CLI —
> the old `/data/db` cannot be reused. See the README "Upgrading" and "Backup &
> restore" sections.


### Features

* **deploy:** single-container bundled mode + external datastores from one image ([f932c09](https://github.com/Bardesss/setvault/commit/f932c090210ebb694e1301121015eae390759497))
* **docker:** 00-mode cont-init resolves bundled/external + /data paths ([0e912d4](https://github.com/Bardesss/setvault/commit/0e912d430e9876bbafd3301174f3071bd4b1775f))
* **docker:** bundle tusd + Caddy proxy; uvicorn binds mode port ([8e48215](https://github.com/Bardesss/setvault/commit/8e4821567d9d4d67ab61ec8d6343d54d397533e3))
* **docker:** bundled Postgres + init-db oneshot; migrate via s6-rc deps ([980e79e](https://github.com/Bardesss/setvault/commit/980e79e0a250fb9e03b25deba705b1c801f13810))
* **docker:** bundled Redis s6 service (idle in external mode) ([daf972e](https://github.com/Bardesss/setvault/commit/daf972ea37f7729a4eeaebfe7842340ceafea11a))
* **docker:** external compose (pg18, tusd bundled) + compose.aio.yml + env docs ([0e31b80](https://github.com/Bardesss/setvault/commit/0e31b8040f878f990b79fac3e9f8833862c664f8))
* **docker:** install PG18, Redis, tusd, Caddy; mode-aware ENV ([06f06d6](https://github.com/Bardesss/setvault/commit/06f06d6e88c2bdb4cd25c68f42c6a67261383efb))
* **docker:** mode-detection lib + unit tests for bundled/external ([9eb2a44](https://github.com/Bardesss/setvault/commit/9eb2a440633834582de4588826ad77e45b68254f))


### Bug Fixes

* **docker:** external-mode boot — PG18 volume path + init-db readiness ([896168b](https://github.com/Bardesss/setvault/commit/896168b39803b89c979c01273e57661b8659ca03))
* **docker:** make bundled single-container image actually boot ([c75ac53](https://github.com/Bardesss/setvault/commit/c75ac53b8846c867158aa52fbbfc53c29affa39d))


### Documentation

* **readme:** bundled vs external install paths + PG18 caveat ([79893c4](https://github.com/Bardesss/setvault/commit/79893c42c9e0acedcc240bd7b47f290cbce1c161))
* **readme:** flip 6D to merged; bundled deploy is the sole this-release row ([6e81756](https://github.com/Bardesss/setvault/commit/6e81756ec6e770284c46495f357badb068b04e15))

## [0.5.0](https://github.com/Bardesss/setvault/compare/v0.4.0...v0.5.0) (2026-06-08)


### Features

* **admin:** connectors adopts AdminTable + EmptyState ([f185249](https://github.com/Bardesss/setvault/commit/f18524937201b3e2a1d38744523486bece3f80f9))
* **admin:** EmptyState, StatusBlock, AdminTable, AdminForm components ([a957a15](https://github.com/Bardesss/setvault/commit/a957a15ed002d7ebdef1d9bf22b8ce69f86d3601))
* **admin:** health adopts StatusBlock/AdminTable/EmptyState ([8955e7f](https://github.com/Bardesss/setvault/commit/8955e7fabb4d5948946c2b7b2f9b68f4344dfbd0))
* **admin:** jobs adopts AdminTable + EmptyState ([1460129](https://github.com/Bardesss/setvault/commit/1460129cabcfda2183acb7c578e083ead4a1812e))
* **admin:** providers adopts AdminTable + AdminForm ([d3fa1c9](https://github.com/Bardesss/setvault/commit/d3fa1c98641bb9220909fd03c9f0ea11bf14bc69))
* **admin:** recycle adopts AdminTable/EmptyState + shared buttons ([1a94ec6](https://github.com/Bardesss/setvault/commit/1a94ec672fefebd0d3c064b399e41cab31db3ee1))
* **admin:** restyle shell to shared chrome (banner + tabs) ([5af9d80](https://github.com/Bardesss/setvault/commit/5af9d80757487109db695a07a2c30661bb769202))
* **admin:** storage adopts AdminTable + EmptyState ([2ea0dcc](https://github.com/Bardesss/setvault/commit/2ea0dcc24138c66a2bc21488b1d932b1cc9a0d54))
* **admin:** system adopts StatusBlock/AdminTable ([b449d02](https://github.com/Bardesss/setvault/commit/b449d021d56bbf983adaae768f573dcd4de9e9de))
* **admin:** tasks adopts AdminTable/EmptyState + shared buttons ([5636fcf](https://github.com/Bardesss/setvault/commit/5636fcf0f7a447ed3dc5a320f773763a2e37fdb9))
* **admin:** unmatched adopts AdminTable/EmptyState + shared buttons ([eb7847d](https://github.com/Bardesss/setvault/commit/eb7847de0ea648005581fc428e8eee0fadae9fd7))
* **admin:** users adopts AdminTable + EmptyState ([c143822](https://github.com/Bardesss/setvault/commit/c143822f182bc3ff87e68de291e6ab5f5d6d5b73))
* **admin:** watch-folders adopts AdminTable/AdminForm/EmptyState ([14b0cbe](https://github.com/Bardesss/setvault/commit/14b0cbe4afe37987d742cb9f054a63f7134a182f))
* **admin:** webhooks adopts AdminTable/AdminForm/EmptyState ([234b607](https://github.com/Bardesss/setvault/commit/234b607b3ba1b4fac4a577454c573869e9b4cebe))
* **phase-6d:** shared admin components across 12 tabs + Settings + Sets/new ([1770f87](https://github.com/Bardesss/setvault/commit/1770f87c95c449fa4b29006ac4f0de8d0b342d4b))
* **sets-new:** design-language pass with shared TabStrip ([f3d4688](https://github.com/Bardesss/setvault/commit/f3d468811bb016d93bc2524f150184362188e31d))
* **settings:** TabStrip layout + shared form/status components ([b3a5bc7](https://github.com/Bardesss/setvault/commit/b3a5bc728c9384ecc3757a5ade989ffcbf973d06))
* **styles:** shared .btn:disabled state ([d707e4e](https://github.com/Bardesss/setvault/commit/d707e4edf57afd0460068c6ef15e5df60582b699))
* **styles:** shared admin chrome classes for Phase 6D ([fe83323](https://github.com/Bardesss/setvault/commit/fe833237787aff01b1357beaf9d2cff4608bb08e))


### Bug Fixes

* **admin:** restore muted style for unmatched picker no-matches row ([adb0e63](https://github.com/Bardesss/setvault/commit/adb0e63f370fbb809b68cf86ad09017097dc79da))
* **styles:** drop duplicate .btn-danger from Phase 6D block ([58366ca](https://github.com/Bardesss/setvault/commit/58366ca293eb499060b9c6e6d231751dad5c3cfb))


### Documentation

* **readme:** mark 6D admin/management as this release ([c784079](https://github.com/Bardesss/setvault/commit/c7840793030a7737b3dbaf27b1073bacf8f4e4dc))

## [0.4.0](https://github.com/Bardesss/setvault/compare/v0.3.0...v0.4.0) (2026-06-02)


### Features

* **phase-6c:** global persistent player + mobile mini/full-screen ([4814b9b](https://github.com/Bardesss/setvault/commit/4814b9b90eb0397f8c25e80ea5c80cf8abe4cc61))
* **player:** audio engine service (stores/audio.ts) for 6C ([9e7b0a1](https://github.com/Bardesss/setvault/commit/9e7b0a1890ab29b5bd0183517a30c1d293db65ba))
* **player:** AudioHost — init engine + app-wide shortcuts (6C) ([029c0c7](https://github.com/Bardesss/setvault/commit/029c0c70f5c91ef1af889f428fc703b8b9dd8339))
* **player:** FullScreenPlayer overlay + fullscreen guard (6C) ([697edd4](https://github.com/Bardesss/setvault/commit/697edd4f8ca12f93c2795a831574900d999c91d4))
* **player:** rewrite MiniPlayer as persistent bottom-sheet (6C) ([563e9dd](https://github.com/Bardesss/setvault/commit/563e9dd7f78ae85ca530482611af8e2b46c38d8e))
* **player:** slim set-page Player onto the audio service (6C) ([5e597a7](https://github.com/Bardesss/setvault/commit/5e597a7a67ffe3ad65cbf9974457b73d8f9b1eed))
* **player:** Waveform view bound to the shared audio element (6C) ([7c16b80](https://github.com/Bardesss/setvault/commit/7c16b809f3cf9f52b6c0b99c7cf975668dff67c1))
* **styles:** mobile mini-player + full-screen player classes (6C) ([c3d680b](https://github.com/Bardesss/setvault/commit/c3d680b917863f2a5dcca7f4f8daeb1a89ba2bb6))


### Bug Fixes

* **player:** attach engine &lt;audio&gt; to the DOM so playback starts (6C) ([a0abc93](https://github.com/Bardesss/setvault/commit/a0abc93d79643c09ef43553ad0e71179c5b51925))
* **player:** render Waveform from URL, not the engine element (6C) ([6bcf36a](https://github.com/Bardesss/setvault/commit/6bcf36a2fc1c709695743c71aef079af6ab22e3d))
* **sw:** don't cache.put 206 range responses — fixes audio playback (6C) ([ee44c64](https://github.com/Bardesss/setvault/commit/ee44c64af93f7d8d45a5d2c1b58161cc2df49fbd))


### Documentation

* **readme:** mark 6C global persistent player as this release ([5d2cf4c](https://github.com/Bardesss/setvault/commit/5d2cf4cade7ef45e8eb69e84f14345e0116765a5))

## [0.3.0](https://github.com/Bardesss/setvault/compare/v0.2.0...v0.3.0) (2026-06-02)


### Features

* **engagement:** TabStrip + SidePanel; flat prop on engagement components ([4306d13](https://github.com/Bardesss/setvault/commit/4306d138d4e5936fbc21ca617a0ed30b4da428c5))
* **phase-6b:** set detail rebuild + engagement SidePanel + tracklist editor ([2cda1bc](https://github.com/Bardesss/setvault/commit/2cda1bc0191f76460f2fa4bde1d467c3493f61db))
* **player:** restyle to wave-stage + transport-bar (01 mockup) ([cb6ee1f](https://github.com/Bardesss/setvault/commit/cb6ee1ffcff9eaf4d17c26c69e5807713bba2561))
* **set-detail:** rebuild to 01 mockup — hero + body-grid + SidePanel ([7bb077f](https://github.com/Bardesss/setvault/commit/7bb077fe72cd26a85bf1b39117410669f6868c02))
* **styles:** set-detail layout classes for Phase 6B ([6c28490](https://github.com/Bardesss/setvault/commit/6c28490d115c38fa1b1bbe0aaec274f0a6b7bca2))
* **tracklist:** accept bracketed [hh:mm:ss] paste timestamps ([cb55ef3](https://github.com/Bardesss/setvault/commit/cb55ef3b7b778dc744f2503088b4e6cddc660552))
* **tracklist:** restyle rows to .track-row (01 mockup) ([9c89515](https://github.com/Bardesss/setvault/commit/9c8951556f8d264d0b6caee6d1d06ce4e7f6c294))


### Documentation

* **readme:** roadmap to Phase 6 mockup-parity split + renumber 7–12 ([6685acd](https://github.com/Bardesss/setvault/commit/6685acd82afd27a7136e31a11561b994612517bb))

## [0.2.0](https://github.com/Bardesss/setvault/compare/v0.1.2...v0.2.0) (2026-05-28)


### Features

* **api:** GET /api/me/home-summary for Phase 6A home KPI grid ([cd5d024](https://github.com/Bardesss/setvault/commit/cd5d024af4fd46e2798e00b6af57b254cdcee387))
* **bookmarks:** FilterBar + grouped-by-set list, restyled cards ([53180ee](https://github.com/Bardesss/setvault/commit/53180eef4e42a97cd8cafd93ca1483ca68423224))
* **components:** FilterBar + SetRow for library / search / bookmarks ([de381d0](https://github.com/Bardesss/setvault/commit/de381d098732d6ea5eeb063e1109d0c6666585c4))
* **components:** RoadmapTag for landing roadmap items ([d7efe43](https://github.com/Bardesss/setvault/commit/d7efe435a89f8b2ad1eb349b643520e83f682623))
* **components:** SectionHeader, KpiGrid+Kpi, ContinueCard, RecentCard ([1efa19b](https://github.com/Bardesss/setvault/commit/1efa19b02a4dec075f694b6b8f66e9e342cd52fd))
* **embed:** compact chrome with brand + Open in SetVault footer ([a7d4ddd](https://github.com/Bardesss/setvault/commit/a7d4ddd51ed4d25e4c546e0b682d3bb6e3fca926))
* **home:** rebuild to match 03-home mockup with KPI grid ([de58271](https://github.com/Bardesss/setvault/commit/de58271f1fc476c92f04c902bd8e03e2cb3971db))
* **invite:** auth-card design language ([be9e40a](https://github.com/Bardesss/setvault/commit/be9e40a407857e747d640b3059c90063696f4430))
* **landing:** port underground-terminal design to deployed site ([98a0bc1](https://github.com/Bardesss/setvault/commit/98a0bc12aa3a1efb0f63d51336d8446d167e1f5b))
* **library:** FilterBar header + list/grid toggle + SetRow ([a4a59ac](https://github.com/Bardesss/setvault/commit/a4a59ac8dacac18d40e9f066321ba1c578ddb4fd))
* **login:** auth-card design language with scanline shell ([4cc86cc](https://github.com/Bardesss/setvault/commit/4cc86cc805063a7fc8a98389bb200d6ed13ea0aa))
* **phase-6a:** first impressions + browse foundation ([21f04de](https://github.com/Bardesss/setvault/commit/21f04de89e372c969bb4761a714d2393812a0e85))
* **reset:** auth-card design language ([192594f](https://github.com/Bardesss/setvault/commit/192594f098e43482c01244013d19ae4c1b54d15a))
* **search:** FilterBar + grouped results design-language ([cf1f5f2](https://github.com/Bardesss/setvault/commit/cf1f5f2f2cfb626d807c613484b36391c947d17a))
* **shell:** TopBar + grouped NavRail per 03-home mockup ([9e3e6ac](https://github.com/Bardesss/setvault/commit/9e3e6ac4449557e91311e2b41c1442469bed4963))
* **shell:** TopBar + grouped NavRail wired into +layout.svelte ([602d503](https://github.com/Bardesss/setvault/commit/602d5036cfdbd8aff59b9f65f951409bd4918073))
* **site:** build-time copy of shared design assets for landing ([595b50f](https://github.com/Bardesss/setvault/commit/595b50fb929f3bfcd776a2e165e14721b4536081))
* **styles:** shared Phase 6A class patterns in components.css ([006adf5](https://github.com/Bardesss/setvault/commit/006adf5ba287560da35b5084c39bdf1f96e2a701))


### Bug Fixes

* **6a:** restore &lt;h1&gt; headings on embed + bookmarks ([2f5ec61](https://github.com/Bardesss/setvault/commit/2f5ec616b772f87a5c1e1e94556d810e853df12c))


### Documentation

* **6a:** design-language pointer in root README + design-package readme refresh ([1e7e8c3](https://github.com/Bardesss/setvault/commit/1e7e8c3bbdafd18b6fec1109d349ecd214d9d116))
* **readme:** bump version refs to v0.1.2 + 6A design-language section ([52602d0](https://github.com/Bardesss/setvault/commit/52602d002f10920419a453009e77146900c831dc))

## [0.1.2](https://github.com/Bardesss/setvault/compare/v0.1.1...v0.1.2) (2026-05-28)

### Features

- **Default HTTP port is now `1970`** (the year of David Mancuso's first
  Loft parties — the year the DJ live set as we know it was born) —
  previously `8000`. Applies to `SETVAULT_HTTP_PORT`, the bundled compose
  file's port mapping, the container's `EXPOSE`, the dev-stack uvicorn
  flag, and the bundled landing's quickstart copy. ([ce490ef](https://github.com/Bardesss/setvault/commit/ce490ef939fa52b5d3762626ee33d21f362ffce8))

  **Breaking change for existing deployments that didn't set
  `SETVAULT_HTTP_PORT` explicitly.** After pulling this version:
  - **If your reverse proxy hits `host:8000`** and you want zero
    operational change, add `SETVAULT_HTTP_PORT=8000` to your `.env`
    before `docker compose up -d`.
  - **If you want the new default**, update the reverse-proxy upstream
    to `host:1970` (or whatever you set `SETVAULT_HTTP_PORT` to) before
    bringing the stack back up.

## [0.1.1] — 2026-05-29

**Noob-friendly self-host.** v0.1.0 shipped two container images
(`setvault-web` + `setvault-worker`) and a six-line `.env` of required
secrets. v0.1.1 collapses that into a **single `setvault` container**
running uvicorn + RQ worker + watchdog under s6-overlay, with **three
required env vars** total and everything else defaulted inside the
image. The self-host compose file drops from six services to four
(`setvault` + `postgres` + `redis` + `tusd`).

### Container

- **Single image**: `ghcr.io/bardesss/setvault:0.1.1` replaces
  `setvault-web` + `setvault-worker`. (Old image names will not be
  republished going forward.)
- **s6-overlay PID 1** supervises uvicorn, the RQ worker, and the
  watchdog watcher. Per-process crashes auto-restart without taking
  down the container.
- **Container-init scripts** (`/etc/cont-init.d/`) run on every boot:
  - `01-defaults` — auto-generates `TUSD_HOOK_SECRET` if missing
    (persisted to `${SETVAULT_CONFIG_PATH}/.secrets`), synthesizes
    `DATABASE_URL` from `POSTGRES_PASSWORD` when no explicit URL is
    given, and chowns bind mounts to `PUID:PGID`.
  - `02-validate` — fails fast with a clear message if required env
    is missing.
  - `03-migrate` — runs `alembic upgrade head` once before any
    longrun starts, with retry-on-postgres-not-ready backoff.
- **Multi-arch fix**: per-arch native binaries (`audiowaveform`,
  `s6-overlay`) are selected from `$TARGETARCH` instead of being
  hardcoded to amd64. v0.1.0's tag attempt failed on the arm64 leg
  because of this; v0.1.1 builds both arches cleanly.
- **Workspace fix**: `packages/providers` (workspace member) is now
  copied into the build context. v0.1.0's `uv sync` failed at
  `Failed to parse entry: setvault-providers`.

### Configuration

- **Required env shrinks to 3**: `SECRET_KEY`, `POSTGRES_PASSWORD`,
  `BASE_URL`. Everything else is defaulted or auto-generated.
- `.env.example` rewritten to a 3-required + commented-optional
  layout (~40 lines, was ~70).
- `compose.example.yml` rewritten to 4 services (was 6).

### Migration from 0.1.0

If you ran v0.1.0:

1. `docker compose pull` — picks up new `setvault:0.1.1` image
2. Replace your `compose.yml` with the new `compose.example.yml`
   (services renamed, fewer of them)
3. Strip `TUSD_HOOK_SECRET` and `PUID`/`PGID` from your `.env` if you
   want — they're defaulted now
4. `docker compose up -d` — `alembic upgrade head` runs automatically
   on first boot

No data migration required; the database schema is unchanged from
0.1.0.

### Fixed

- v0.1.0 docker workflow could not publish on multi-arch tag pushes
  (#23 fix landed but didn't cover the arch issue). v0.1.1 fixes both.
- Old separate Dockerfiles deleted; only `infra/docker/Dockerfile`
  remains.

---

## [0.1.0] — 2026-05-28

**The inaugural release.** Eleven months of design, twenty-one merged
phase PRs, and one private group of DJ-music nerds finally getting the
self-hosted vault they always wanted. SetVault v0.1.0 is the first
publicly tagged build — multi-arch container images on GHCR, SBOMs on
every artifact, cosign signatures on every push.

### Why this exists

Mixcloud went paywall. SoundCloud kept rotting. 1001tracklists is a
read-only museum. Nothing on the market combines **lossless live-set
storage**, **time-coded tracklists**, **provider-enriched metadata**, and
a **private streaming player you actually own** — for the specific shape
of DJ live sets, not for individual tracks. SetVault is that
combination, self-hosted, GPL-3.0, ready to live behind your reverse
proxy.

### ✨ Highlights

- **Resumable multi-GB uploads** via tus.io — pause your laptop, resume
  on your phone
- **Paste-URL ingest** from YouTube / SoundCloud / Mixcloud / Internet
  Archive / Bandcamp via `yt-dlp` (SSRF-allowlisted, rate-limited)
- **Watch-folder auto-ingest** — drop files into a host directory and
  SetVault picks them up via `watchdog`
- **Time-coded tracklists** with paste-parse, OCR import, 1001tracklists
  scrape, and an in-player **M-key live add**
- **Provider-enriched metadata** — pluggable framework, MusicBrainz +
  Discogs + AcoustID shipped, response cache + per-field priority + locks
- **wavesurfer.js player** with variable speed (0.5×–2×, pitch-preserved),
  A↔B looping, persisted per-user position, and `mediaSession` controls
  that jump between tracklist entries
- **Engagement layer**: comments with `@mentions` and waveform markers,
  per-set + timestamped bookmarks, private notes, in-app + email
  notifications
- **Per-user RSS feeds** (favorites / recent / everything) with
  `ApiToken` auth and HMAC-signed short-TTL enclosure URLs
- **Embeddable `/embed/[slug]` player** with admin `embed_allowed` toggle
  and a dedicated per-route CSP
- **Installable PWA** with offline set-detail, audio cache cap (admin-
  configurable, oldest-first eviction) and a phone-width pass across the
  whole UI
- **Internationalization-ready** via Crowdin GitHub Integration — English
  source, de / es / fr / nl stubs in place
- **Hardened by default** — Argon2 password hashing, CSRF middleware,
  strict CSP + HSTS, SSRF allowlist on URL-rip, rate-limited login,
  `no-new-privileges` + `cap_drop: ALL` on every container

### Ingest

- ffmpeg → Opus transcode with EBU R128 loudness measurement
- waveform peak extraction cached on disk
- chromaprint dedup via AcoustID fingerprints
- per-`MediaRoot` naming templates
- URL-rip rate limit: 5/hour, 50/day per user

### Catalog

- LiveSet model with first-class Artists, Venues, Series, Parties, Tags,
  and MediaRoots
- Postgres full-text search across titles, artists, tags, venues
- Soft delete with a 14-day purge grace and a recycle-bin UI
- Bulk editor: `soft_delete` / `retag` / `move_root` over selected sets

### Player polish (§5D)

- Variable speed slider (0.5× – 2.0×, 0.05 step) with pitch preservation
- A↔B loop region (`[` set A, `]` set B, `\` clear) with visual band
- Playback rate persisted per user per set via `UserSetState`
- Keyboard: `space` play/pause, `←` `→` seek, `<` `>` rate ±0.05,
  `[` `]` `\` loop, `M` live-add tracklist entry

### Admin surface (§5C)

- Library webhooks with HMAC signing and exponential-backoff retries
- Scheduled tasks (cron-style + `rq-scheduler`)
- Storage health monitor (capacity per `MediaRoot`, oversized-set alarms)
- Watch-folder configuration UI with unmatched-file queue
- Streaming backup endpoint (`pg_dump` + `tar` over chunked response)

### PWA (§4C / §5E)

- Manifest + maskable icons + theme-color
- Service worker: cache-first static, network-first navigation, audio
  cache-first with capacity enforcement
- Offline set-detail page works after first online load
- Audio cap is admin-configurable; lowering it triggers immediate
  eviction via a `MessageChannel` round-trip
- Phone-width responsive across login / library / set detail / settings

### Distribution (§4B)

- Per-user RSS at `/api/feeds/{kind}/feed.rss?token=...` (kinds:
  `favorites`, `recent`, `everything`)
- `ApiToken` model with revocable tokens, listed in settings
- HMAC-signed enclosure URLs with admin-configurable TTL (default 1 h)
- Embeddable player at `/embed/[slug]` with per-route CSP allowing
  `frame-ancestors *`

### Internationalization

- Source strings: 145 keys in `frontend/src/lib/i18n/locales/en.json`
- de / es / fr / nl scaffolded; svelte-i18n falls back to English while
  Crowdin contributors catch up
- Crowdin GitHub Integration handles both directions automatically

### Tech stack

- **Backend**: FastAPI on async SQLAlchemy 2 (Postgres 16), Redis 7 + RQ
  + `rq-scheduler`, Alembic migrations, structlog
- **Frontend**: SvelteKit (adapter-static, bundled into the web image),
  wavesurfer.js 7, svelte-i18n
- **Workers**: Python `rq` worker + a `watchdog`-driven watcher process
- **Uploads**: tusd resumable-upload sidecar
- **Audio**: ffmpeg, fpcalc (chromaprint), pytesseract
- **Containers**: multi-arch (`linux/amd64`, `linux/arm64`) images on
  `ghcr.io`

### Security

- Argon2 password hashing
- HMAC-signed short-TTL share URLs (`signed_urls.py`)
- Pure-ASGI CSRF + SecurityHeaders middleware (no `BaseHTTPMiddleware`
  task-group races)
- Strict CSP, HSTS, X-Frame-Options DENY, Permissions-Policy locked down
- SSRF allowlist on URL-rip ingest
- Rate-limited login + URL-rip via Redis
- `security_opt: no-new-privileges` + `cap_drop: ALL` on every container
- `yt-dlp` exact-pinned with an `infra/scripts/update-yt-dlp.sh` updater

### Release engineering (§5F)

- Conventional commits + [release-please](https://github.com/googleapis/release-please)
  managing future tags and `CHANGELOG.md`
- Container images published to GHCR on every `v*` tag
- **SBOM** (CycloneDX, via Syft) attached to each release
- **Cosign keyless signatures** on each published image (verify with
  `cosign verify --certificate-identity-regexp ...`)
- `infra/docker/compose.example.yml` — copy-paste self-host stack that
  pulls from GHCR (no local build needed)
- Expanded `.env.example` documenting every configurable variable

### Known follow-ups (post-v0.1.0)

- Real-device PWA install screenshots (headless tests cover manifest +
  icons + SW registration; `beforeinstallprompt` requires a real device)
- Crowdin translations land back as they're completed by contributors
- Phase 6 — ingest power tools (interactive search, monitored entities,
  quality preferences, upgrade-available flow)
- Phases 7–11 per `README.md` (Subsonic, casting, Sonos, smart playlists,
  OIDC + forward-auth)

### Co-authored

The vast majority of this codebase was pair-programmed with Claude Code
(Opus 4.x). Every change is reviewed, tested, and shipped by the human
maintainer — but the commits are marked with `Co-Authored-By` and the
contribution shape is honest.

---

[0.1.1]: https://github.com/Bardesss/setvault/releases/tag/v0.1.1
[0.1.0]: https://github.com/Bardesss/setvault/releases/tag/v0.1.0
