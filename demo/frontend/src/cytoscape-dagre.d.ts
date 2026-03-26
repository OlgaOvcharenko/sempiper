declare module "cytoscape-dagre" {
  import type { Core } from "cytoscape";
  const register: (cytoscape: typeof Core) => void;
  export default register;
}
