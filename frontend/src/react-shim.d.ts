// Kept only for offline development environments where npm cannot fetch @types.
// Published installs use the @types/react and @types/react-dom dev dependencies.
declare namespace JSX { interface IntrinsicElements { input: { type?: string; checked?: boolean; onChange?: (event: { target: { checked: boolean } }) => void; disabled?: boolean }; select: { value?: string; onChange?: (event: { target: { value: string } }) => void; children?: any }; [elementName: string]: any } }
declare module "react" {
  export type SetStateAction<T> = T | ((previous: T) => T);
  export type Dispatch<T> = (value: T) => void;
  export function useState<T>(initial: T): [T, Dispatch<SetStateAction<T>>];
  export function useEffect(effect: () => void | (() => void), deps?: unknown[]): void;
  export function useCallback<T extends (...args: any[]) => any>(callback: T, deps: unknown[]): T;
  export function useMemo<T>(factory: () => T, deps: unknown[]): T;
  export function useRef<T>(initial: T): { current: T };
  export const StrictMode: any;
}
declare module "react/jsx-runtime" { export const jsx: any; export const jsxs: any; export const Fragment: any; }
declare module "react-dom/client" { export function createRoot(element: Element | DocumentFragment): { render(node: any): void }; }
