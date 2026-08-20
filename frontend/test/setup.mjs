import { register } from "node:module";

// Hooks run on their own thread, hence the separate module.
register("./alias-hooks.mjs", import.meta.url);
