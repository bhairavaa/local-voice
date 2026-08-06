import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  // Generated from the engine's OpenAPI document; not authored here, so not linted here.
  { ignores: ["dist", "src/services/generated"] },
  js.configs.recommended,
  ...tseslint.configs.strict,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/consistent-type-imports": "error",
      // debug and info are allowed for deliberate breadcrumbs across the Rust/webview
      // boundary, where a silent failure is otherwise indistinguishable from a feature that
      // simply does not work. Bare console.log remains banned.
      "no-console": ["error", { allow: ["warn", "error", "info", "debug"] }],
    },
  },
);
