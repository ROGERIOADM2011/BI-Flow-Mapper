# Contributing to BI Flow Mapper

Thank you for your interest in contributing to BI Flow Mapper! This document provides guidelines for contributing to the project.

## Table of Contents

- [Getting Started](#getting-started)
- [How to Contribute](#how-to-contribute)
- [Development Setup](#development-setup)
- [Code Style](#code-style)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)

## Getting Started

BI Flow Mapper is an open-source Power BI lineage visualization tool. Before contributing, please:

1. Read the [README.md](README.md) to understand the project
2. Check existing [issues](https://github.com/ROGERIOADM2011/BI-Flow-Mapper/issues) and [pull requests](https://github.com/ROGERIOADM2011/BI-Flow-Mapper/pulls)
3. Join discussions to understand current priorities

## How to Contribute

You can contribute in several ways:

### Reporting Bugs

If you find a bug, please create an issue with:
- Clear description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Screenshots if applicable
- Your environment (OS, Python version, browser)

### Suggesting Features

For feature requests:
- Describe the feature and use case
- Explain why it would benefit users
- Consider including mockups or examples

### Code Contributions

We welcome pull requests for:
- Bug fixes
- New features
- Documentation improvements
- Performance optimizations
- Test coverage

## Development Setup

### Prerequisites

- Python 3.8+ (3.10+ recommended)
- pip
- Git

### Local Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/BI-Flow-Mapper.git
cd BI-Flow-Mapper

# Install dependencies
pip install -r requirements.txt

# Run in browser mode
python backend.py
```

### Project Structure

```
bi-flow-mapper/
├── index.html              # Single-page application
├── app.js                  # Frontend logic
├── styles.css              # UI styles
├── backend.py              # HTTP server + pbixray analysis
├── main_app.py             # Desktop launcher (pywebview)
├── connector_catalog.py    # Power Query connectors
├── pbip_reader.py          # Native .pbip (TMDL + PBIR) reader
└── requirements.txt        # Python dependencies
```

## Code Style

### Python

- Follow [PEP 8](https://pep8.org/) style guide
- Use meaningful variable names
- Add docstrings for functions and classes
- Keep functions focused and reasonably sized

### JavaScript

- Use modern ES6+ syntax
- Use `const` and `let`, not `var`
- Write clear comments for complex logic
- Keep functions focused and testable

### General

- Write clear commit messages
- Comment non-obvious code
- Avoid adding unnecessary dependencies
- Keep PRs focused on a single change

## Testing

Before submitting changes:

1. **Test manually**: Load various `.pbix` and `.pbip` files
2. **Check all tabs**: Map, Relationships, Architecture, Pages
3. **Test exports**: JSON, PNG, Word documentation
4. **Browser compatibility**: Test in Chrome, Firefox, Edge
5. **Desktop mode**: If you modified the desktop launcher

If you're adding a feature, consider including test cases or examples.

## Submitting Changes

### Pull Request Process

1. **Fork** the repository
2. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make your changes** with clear commits
4. **Test thoroughly** (see [Testing](#testing))
5. **Update documentation** if needed
6. **Submit a pull request** with:
   - Clear title and description
   - Reference to any related issues
   - Screenshots/examples if applicable

### Pull Request Guidelines

- Keep PRs focused on a single change
- Write clear commit messages
- Update README/docs if adding features
- Respond to review feedback promptly
- Ensure your branch is up to date with main

### Commit Messages

Write clear, descriptive commit messages:

```
Add native .pbip folder support via directory picker

- Implement folder picker for .pbip projects
- Add TMDL and PBIR parsing
- Include UI button for folder selection
```

## Questions?

If you have questions:
- Open a [discussion](https://github.com/ROGERIOADM2011/BI-Flow-Mapper/discussions)
- Comment on a relevant issue
- Check existing documentation

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

## Credits

This project is a fork of [JoseMalan's BI Flow Mapper](https://github.com/JoseMalan/BI-Flow-Mapper). 

The native `.pbip` reader and related features were contributed by Rogério Alves Rocha de Souza.
