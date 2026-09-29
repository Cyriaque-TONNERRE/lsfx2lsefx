# lsfx2lsefx — BG3 effect decompiler

Rebuilds the editable source of a Baldur's Gate 3 visual effect (`.lsefx`, the file opened by the Toolkit's AllSpark effect editor) from a compiled effect (`.lsfx`, the file the game loads).

Many vanilla effects ship only as compiled `.lsfx`. The Toolkit lets you duplicate them, but the editor then refuses to open them ("Can not open the Effect file because it does not exists!"). This tool recreates the missing source, so you can open the effect in the editor and edit it: remove or add components, change timings, tweak curves and colors.

> Unofficial community tool, not affiliated with or endorsed by Larian Studios. Always work on copies of your files.

## Requirements

- Python 3.8 or newer. No extra packages are needed.
- The BG3 Toolkit installed. The tool reads two editor definition files that ship with it:
  `...\Baldurs Gate 3\Data\Editor\Config\AllSpark\ComponentDefinition.xcd`
  `...\Baldurs Gate 3\Data\Editor\Config\AllSpark\ModuleDefinition.xmd`
  These files are **not** included; use your own copies.

## Files

Keep these 8 files together in the same folder:

| File | Role |
|---|---|
| `lsfx2lsefx.py` | The converter (the script you run) |
| `lsfx_read.py` | Reads the `.lsfx` into a node tree |
| `lsf2.py` | LSF binary format parser |
| `lsfc.py` | LSF section decompression |
| `lz4b.py` | LZ4 decompression |
| `defs.py` | Reads the editor definitions (`.xcd` / `.xmd`) |
| `curvefit.py` | Recovers the original Spline / Bézier curves |
| `rampcompile.py` | Re-implementation of the editor's curve compiler, used to verify every rebuilt curve |

## Usage

```
python lsfx2lsefx.py <effect.lsfx> [more.lsfx ...] -o <output folder> --defs "<...\Data\Editor\Config\AllSpark>"
```

Example:

```
python lsfx2lsefx.py "C:\...\Data\Public\MyMod\Assets\Effects\Effects_Banks\MyEffect.lsfx" -o out --defs "C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3\Data\Editor\Config\AllSpark"
```

If the game is installed in the default Steam folder, `--auto-defs` finds the definitions for you:

```
python lsfx2lsefx.py MyEffect.lsfx -o out --auto-defs
```

It looks in `C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3\Data\Editor\Config\AllSpark`. If the files are not there (for example, the game is in another Steam library), the tool stops with a message: use `--defs` with the right folder instead.

- The input must be the **compiled `.lsfx`** (usually under `Data\Public\<mod>\Assets\Effects\Effects_Banks\`), not a `.lsefx`. Other files are rejected with a message.
- `-o` can be an output folder, or a `.lsefx` file name when you convert a single effect. Without `-o`, the result is written next to the input.
- Without `--defs` or `--auto-defs`, the tool looks for a `Definitions` folder next to the scripts. If the definition files are missing, it stops with a message saying which ones.
- The tool never overwrites its input or an existing file inside the game folder.
- Optional: `--names names.txt`, a text file with one `guid name` pair per line, to show resource names (materials, meshes...) in the editor. Without it, resource fields contain the GUID only, which the editor and the compiler accept.

Conversion takes a few seconds for small effects and about a minute for large ones (30+ components).

## Accuracy

Tested on 12 effects: small custom ones and large vanilla-based ones with particles, models, lights, overlay materials and sounds.

- **Properties**: identical to the original sources (5,296 of 5,296 values).
- **Curves**: Linear and Spline curves come back exactly. Free-tangent (Bézier) curves are rebuilt from the compiled data by solving the compiler's own math. Every rebuilt curve is recompiled and checked against the original, and in the simulated round trip all 557 curves compile back to the same data. In a few cases the control points differ from the original ones but give the same curve.
- **Round trip in the Toolkit**: decompiling, opening, saving and recompiling an effect gives the same compiled data, apart from rounding differences around 1e-5 caused by the 7-digit precision of the `.lsefx` format.

## Limitations

Some information is dropped by the compiler and cannot be recovered:

- track and track-group names (all are named "Track" / "New Track Group"); each component gets its own track;
- muted components and muted tracks;
- resource display names (see `--names`);
- editor UI state (selected channels, expanded properties).

Also:

- Older `.lsfx` files do not store which modules were enabled. The tool enables a module when one of its properties has a non-default value. A module left at its default values may be missing; you can add it back in the editor, and the in-game effect is unchanged.
- Sampled color curves (free-tangent color ramps) are converted to Linear color keys.

## How it works (short version)

1. The `.lsfx` (LSF binary, LZ4-compressed) is decoded into a tree: `Effect > EffectComponents > EffectComponent > Properties / Modules`.
2. Each property's `FullName` (for example `Appearance.Size`) is matched against the property groups in `ComponentDefinition.xcd` to get the property GUID the editor uses.
3. Values are written in the editor's formats (7 significant digits, comma-separated vectors, signed ARGB colors...).
4. Compiled curves are piecewise cubic Hermite polynomials. The tool finds the Bézier control points that produce exactly those pieces, then checks them by recompiling.

## License

[MIT](LICENSE)
