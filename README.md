# Gaussian Elimination Trainer

An interactive, browser-based tool for learning and practicing Gaussian elimination with exact rational arithmetic.

Created by Sebastian Bozlee at Wake Forest University, with development assistance from ChatGPT.

## Live site

After enabling GitHub Pages, the app will be available at:

```text
https://YOUR-USERNAME.github.io/gaussian-elimination-trainer/
```

## Modes

- **Guided mode** leads students through Gaussian elimination while requiring them to choose operations, rows, and factors. Incorrect choices receive graduated feedback.
- **Practice mode** lets students choose their own strategy and requires them to enter the resulting row after scaling or row replacement.
- **Free mode** performs valid elementary row operations automatically and is useful for demonstrations and exploratory work.

The app supports exact fractions, undo/redo, several categories of generated practice problems, mobile rational-number entry, LaTeX/PDF export on desktop, and responsive layouts for phones and computers.

## Run locally

No build step is required. Open `index.html` in a modern browser.

For a more representative local deployment, serve the repository with a simple HTTP server:

```bash
python -m http.server 8000
```

Then open `http://localhost:8000`.

## Publish with GitHub Pages

1. Create a GitHub repository named `gaussian-elimination-trainer`.
2. Commit these files and push the `main` branch.
3. In the repository, open **Settings → Pages**.
4. Under **Build and deployment**, choose **Deploy from a branch**.
5. Select `main` and `/ (root)`, then save.

GitHub Pages will serve `index.html` automatically.

The included `.nojekyll` file tells GitHub Pages to serve the static files directly without Jekyll processing.

## UI regression tests

The repository includes a browser interaction harness in `tests/ui_tests.py`. It exercises Guided, Practice, and Free modes at compact Android portrait, standard Android portrait, mobile landscape, and desktop viewport sizes. It checks element overlap, prompt and input visibility, page/history scrolling, workspace transitions, and browser console errors.

See [`docs/UI_TESTING.md`](docs/UI_TESTING.md) for setup and usage details.

## Project status

The tool is usable in class and by students, but it remains under active pedagogical and interface development. Bug reports and suggestions are welcome through GitHub Issues.

## Credits

Gaussian Elimination Trainer is developed by Sebastian Bozlee, Wake Forest University. ChatGPT assisted with implementation, interface iteration, documentation, and testing support.

## License

Released under the MIT License. See [`LICENSE`](LICENSE).
