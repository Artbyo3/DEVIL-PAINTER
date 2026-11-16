# Devil Painter

A Blender add-on bringing layer-based texture painting into Blender.

> Validation stage: project structure and CI skeleton only. Texture-painting features are not implemented yet.

![AI disclosure: this project was created entirely with AI tools](https://img.shields.io/badge/AI%20disclosure-created%20entirely%20with%20AI%20tools-informational?style=flat-square)

This project was created entirely with AI tools.

## Requirements

- Blender 5.2+

## Development

Build the extension archive:

```sh
python tools/build.py
```

Run checks:

```sh
python -m unittest discover -s tests -p "test_*.py" -v
python tools/check_public.py
```

## Links

- [Repository](https://github.com/Artbyo3/DEVIL-PAINTER)
- [Issues](https://github.com/Artbyo3/DEVIL-PAINTER/issues)
- License: [GPL-3.0-or-later](LICENSE)
