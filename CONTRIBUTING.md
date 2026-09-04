# Contribution guidelines

Contributing to this project should be as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features

## Github is used for everything

Github is used to host code, to track issues and feature requests, as well as accept pull requests.

Pull requests are the best way to propose changes to the codebase.

1. Fork the repo and create your branch from `main`.
2. If you've changed something, update the documentation.
3. Make sure your code lints (using `scripts/lint`).
4. Test you contribution.
5. Issue that pull request!

## Any contributions you make will be under the MIT Software License

In short, when you submit code changes, your submissions are understood to be under the same [MIT License](http://choosealicense.com/licenses/mit/) that covers the project. Feel free to contact the maintainers if that's a concern.

## Report bugs using Github's [issues](../../issues)

GitHub issues are used to track public bugs.
Report a bug by [opening a new issue](../../issues/new/choose); it's that easy!

## Write bug reports with detail, background, and sample code

**Great Bug Reports** tend to have:

- A quick summary and/or background
- Steps to reproduce
  - Be specific!
  - Give sample code if you can.
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening, or stuff you tried that didn't work)

People *love* thorough bug reports. I'm not even kidding.

## Use a Consistent Coding Style

Use [black](https://github.com/ambv/black) to make sure the code follows the style.

## Test your code modification

This custom component is based on [integration_blueprint template](https://github.com/ludeeus/integration_blueprint).

It comes with development environment in a container, easy to launch
if you use Visual Studio Code. With this container you will have a stand alone
Home Assistant instance running and already configured with the included
[`configuration.yaml`](./config/configuration.yaml)
file.

### Getting started with VS Code Dev Containers

1. Install the [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) extension and Docker.
2. Open this repository in VS Code and choose **Dev Containers: Reopen in Container** (the configuration lives in [`.devcontainer/devcontainer.json`](./.devcontainer/devcontainer.json)).
3. Wait for `postCreateCommand` to finish; it installs the required apt packages (`ffmpeg`, `libturbojpeg0`, `libpcap-dev`) and runs `scripts/setup` to install Python dependencies from `requirements.txt`.

### Starting Home Assistant locally

- Run the VS Code task **Start Home Assistant (port 8123)** (Terminal → Run Task…), or execute `scripts/develop` directly.
- Once started, open [http://localhost:8123](http://localhost:8123) (VS Code will also offer to forward the port automatically).
- Use the **Run Lint** task or `scripts/lint` to run Ruff.

### GitHub Copilot in the container

`GitHub.copilot` and `GitHub.copilot-chat` are installed automatically inside the container, but you still need to sign in manually:

1. After the container has finished building, open the **Accounts** menu (bottom left) or run **GitHub Copilot: Sign in** from the command palette.
2. Complete the sign-in with your GitHub account in the browser.
3. Reload the window (**Developer: Reload Window**) if Copilot doesn't activate immediately.

No credentials or tokens are stored in this repository; the sign-in is a manual, per-user step.

## License

By contributing, you agree that your contributions will be licensed under its MIT License.
