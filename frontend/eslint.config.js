import js from "@eslint/js";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

export default [
  { ignores: ["dist/", "node_modules/"] },
  js.configs.recommended,
  react.configs.flat.recommended,
  react.configs.flat["jsx-runtime"],
  reactHooks.configs.flat["recommended-latest"] ?? reactHooks.configs["recommended-latest"],
  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: { ...globals.browser, __APP_VERSION__: "readonly" },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    settings: { react: { version: "detect" } },
    rules: {
      "react/prop-types": "off",
      // Apostrophes and quotes in UI text are fine; still catch the characters that break JSX
      "react/no-unescaped-entities": ["error", { forbid: [">", "}"] }],
      // Pages load their data in effects (the pattern in React's docs); the alternative this
      // rule pushes towards is a data-fetching library, which the app doesn't use
      "react-hooks/set-state-in-effect": "off",
      "no-unused-vars": ["error", { argsIgnorePattern: "^_", caughtErrors: "none" }],
    },
  },
  {
    files: ["vite.config.js", "eslint.config.js", "**/*.test.{js,jsx}"],
    languageOptions: { globals: globals.node },
  },
];
