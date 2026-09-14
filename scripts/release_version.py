"""Read the release version without importing runtime dependencies."""
import argparse
import ast
import re
from pathlib import Path


def release_version(tag=''):
    source = Path(__file__).resolve().parents[1] / 'src/blrec/__init__.py'
    tree = ast.parse(source.read_text(encoding='utf8'))
    version = next(ast.literal_eval(node.value) for node in tree.body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == '__version__'
                           for target in node.targets))
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Release version must be MAJOR.MINOR.PATCH')
    if tag and tag != 'v' + version:
        raise ValueError(f'Tag {tag!r} does not match version {version!r}')
    return version


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', default='')
    print(release_version(parser.parse_args().tag))
