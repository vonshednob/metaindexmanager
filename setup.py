import setuptools
import pathlib

try:
    import docutils.core
    from docutils.writers import manpage
except ImportError:
    docutils = None
    manpage = None

from metaindexmanager import version


with open('README.md', encoding='utf-8') as fd:
    long_description = fd.read()


with open('LICENSE', encoding='utf-8') as fd:
    licensetext = fd.read()


def compile_documentation():
    htmlfiles = []

    if docutils is None:
        return htmlfiles

    dst = pathlib.Path('./metaindexmanager/docs')
    dst.mkdir(exist_ok=True)
    
    pathlib.Path('./man').mkdir(exist_ok=True)

    man_metaindexmanager = None

    if None not in [docutils, manpage]:
        for fn in pathlib.Path('./doc').iterdir():
            if fn.suffix == '.rst':
                if fn.stem == 'metaindexmanager':
                    man_metaindexmanager = str(fn)
                dstfn = str(dst / (fn.stem + '.html'))
                docutils.core.publish_file(source_path=str(fn),
                                           destination_path=dstfn,
                                           writer_name='html')
                htmlfiles.append('docs/' + fn.stem + '.html')

    if man_metaindexmanager is not None:
        docutils.core.publish_file(source_path=man_metaindexmanager,
                                   destination_path='man/metaindexmanager.1',
                                   writer_name='manpage')

    return htmlfiles


setuptools.setup(
    name='metaindexmanager',
    version=version.__version__,
    description="Console UI to browse metaindex file(s).",
    long_description=long_description,
    long_description_content_type='text/markdown',
    url="https://github.com/vonshednob/metaindexmanager",
    author="R",
    author_email="devel+metaindexmanager@kakaomilchkuh.de",
    entry_points={'console_scripts': ['metaindexmanager=metaindexmanager.main:run'],
                  'gui_scripts': []},
    packages=['metaindexmanager'],
    package_data={'metaindexmanager': compile_documentation()},
    data_files=[('share/man/man1', ['man/metaindexmanager.1']),
                ('share/applications', ['extras/metaindexmanager.desktop',]),
                ('share/doc/metaindexmanager', ['extras/mtattach.sh'])],
    install_requires=['metaindex>=0.4.0', 'cursedspace>=1.3.1'],
    extras_require={},
    python_requires='>=3.8',
    classifiers=['Development Status :: 3 - Alpha',
                 'Environment :: Console :: Curses',
                 'Intended Audience :: End Users/Desktop',
                 'License :: OSI Approved :: MIT License',
                 'Natural Language :: English',
                 'Programming Language :: Python :: 3',])

