export async function saveRecord(): Promise<void> {
  try {
    await persistRecord();
  } catch (error) {
    console.error("Saving record failed", error);
  }
}

const example = "catch {}";
