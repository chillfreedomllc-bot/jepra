# kirinuki

ゲーム実況の生素材から、盛り上がっている場所を見つけて切り出すツール。

本体と使い方は [`kirinuki/`](kirinuki/) にあります。

```bash
cd kirinuki
pip install -e .
kirinuki scan 実況.mp4
```

Windows なら `kirinuki/` の中の `.bat` に動画をドラッグするだけでも動きます。

---

このリポジトリには以前、越境BtoBの営業支援ツール（JEPRA）が入っていました。
その事業は行わないことになったため削除しています。必要になった場合は
コミット `398d47b` から取り出せます。

```bash
git checkout 398d47b -- src docs data scripts tests pyproject.toml
```
