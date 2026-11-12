// Read-aloud (TTS) feature. Integration contract: see useReadAloud.ts and docs/ARCHITECTURE.md (TTS).
export { useReadAloud, wordToGroup } from "./useReadAloud";
export { ReadAloudBar } from "./ReadAloudBar";
export { useReadAloudShortcuts } from "./useReadAloudShortcuts";
export type { AudioSegment, ReadAloud, ReadAloudOptions, ReadAloudStatus } from "./types";
