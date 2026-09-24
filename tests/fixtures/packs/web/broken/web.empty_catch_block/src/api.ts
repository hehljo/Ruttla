export async function saveRecord(): Promise<void> {
  try {
    await persistRecord();
  } catch {}
}
