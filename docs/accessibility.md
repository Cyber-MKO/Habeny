# Accessibility review

Target: WCAG 2.1 level AA for the web interface.

## How it was checked

- **Automated:** [axe-core](https://github.com/dequelabs/axe-core) 4 in Chromium, on every
  page (22 including sign-in).
  - at 1280 px and 390 px wide (a phone)
  - in English and French
  - signed in as an admin, with containers in the list, so tables and actions are rendered
- **Manual:**
  - keyboard only: the skip link, the sidebar and the phone menu (Escape closes it), and
    confirmation and edit dialogs (focus moves in, Tab stays inside, Escape cancels, focus
    returns to the button that opened it)
  - zoom to 200%
  - phone-width screenshots of every page
- **Regression tests:** `frontend/src/components/Confirm.test.jsx` covers the dialogs;
  `npm test` checks that every text has a translation.

## Result

The latest run found **0 violations** on every page, at both widths and in both languages.
What the first run found, and what fixed it:

| Issue (axe rule) | Where | Fix |
|---|---|---|
| Form fields without labels (`label`, `select-name`) | 58 controls on 10 pages | Every label is tied to its control (`htmlFor`/`id`) |
| Text contrast below 4.5:1 (`color-contrast`) | Muted text, table headers, danger buttons | Muted text colour raised to #848e9b; danger text lightened |
| No main landmark, content outside landmarks (`landmark-one-main`, `region`) | Every page | `<main>`, labelled navigation, skip link |
| No level-one heading (`page-has-heading-one`) | Every page | Page titles are `<h1>`, section titles `<h2>` |
| Empty table headers (`empty-table-header`) | Action columns | Visually hidden header text |
| Scrollable areas not reachable by keyboard (`scrollable-region-focusable`) | Wide tables and code samples on phones | Focusable (and labelled) while they scroll |

Also fixed, beyond what axe reports:

- **Confirmations:** browser `confirm()` popups (unlabelled and unstylable) replaced by
  proper dialogs. Big deletions ask you to type a word.
- **Toasts:** announced to screen readers through a live region, and closed with a real
  button.
- **Focus:** keyboard focus is always visible (`:focus-visible` outline).
- **Charts:** they have text alternatives (latest, lowest and highest value).
- **Console:** the terminal runs in xterm's screen-reader mode.
- **Phones:** the sidebar becomes a menu button and drawer, so the whole app is usable on a
  phone.
- **Motion:** it's reduced for people who ask for it (`prefers-reduced-motion`).

## Known gaps

- No test with real screen readers (NVDA, JAWS, VoiceOver) yet. The structure
  (landmarks, labels, live regions, dialog semantics) is what they rely on, but a session
  with them is the next step.
- Messages coming from the server (errors, activity descriptions) are English only.
- The interface has a dark theme only; there's no high-contrast or light theme.

## Re-running the check

Build the frontend, start Habeny with some containers, then run axe on each page, for
example with Playwright:

```js
await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
const { violations } = await page.evaluate(() => axe.run(document));
```
