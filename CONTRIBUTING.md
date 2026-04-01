# Contributing to Deepfreeze

All contributions are welcome: ideas, patches, documentation, bug reports,
complaints, etc!

Programming is not a required skill, and there are many ways to help out!
It is more important to us that you are able to contribute.

## Have a Question? Or an Idea or Feature Request?

* File a ticket on [github](https://github.com/elastic/deepfreeze/issues)

## Something Not Working? Found a Bug?

If you think you found a bug, it probably is a bug.

* File it on [github](https://github.com/elastic/deepfreeze/issues)

# Contributing Documentation and Code Changes

If you have a bugfix or new feature that you would like to contribute to
Deepfreeze, and you think it will take more than a few minutes to produce the fix
(ie; write code), it is worth discussing the change with the Deepfreeze users and
developers first! You can reach us via
[github](https://github.com/elastic/deepfreeze/issues).

## Development Setup

```bash
git clone https://github.com/elastic/deepfreeze.git
cd deepfreeze
./install.sh --dev
```

Or install manually:

```bash
pip install -e packages/deepfreeze-core[dev]
pip install -e packages/deepfreeze-cli[dev]
pip install -e packages/deepfreeze-server[dev]
```

## Contribution Steps

1. Test your changes! Run the unit test suite:
   ```bash
   pytest tests/cli/ -v
   ```

   Integration tests require a running Elasticsearch cluster and a config file.
   Set `DEEPFREEZE_TEST_CONFIG` to point to your test config, or place it at
   `~/.deepfreeze/config.yml`. **Integration tests may modify cluster state —
   use a dedicated test cluster, not production.**
   ```bash
   DEEPFREEZE_TEST_CONFIG=/path/to/test-config.yml pytest tests/integration/ -v -m integration
   ```

2. Please make sure you have signed our [Contributor License
   Agreement](http://www.elastic.co/contributor-agreement/). We are not
   asking you to assign copyright to us, but to give us the right to distribute
   your code without restriction. We ask this of all contributors in order to
   assure our users of the origin and continuing existence of the code. You
   only need to sign the CLA once.
3. Send a pull request! Push your changes to your fork of the repository and
   [submit a pull
   request](https://help.github.com/articles/using-pull-requests). In the pull
   request, describe what your changes do and mention any bugs/issues related
   to the pull request.
