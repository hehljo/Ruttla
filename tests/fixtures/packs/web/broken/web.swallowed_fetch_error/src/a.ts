const res = await fetch(u);
if (res.ok) {
  setData(await res.json());
}
