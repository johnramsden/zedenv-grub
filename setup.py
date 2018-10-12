from setuptools import setup, find_packages

from zedenv import __version__

tests_require = [
    'coverage',
    'pytest',
    'pytest-runner',
    'pytest-cov',
    'pytest-pep8',
    'tox'
]

dev_require = [
    'Sphinx'
]


def readme():
    with open('README.rst') as f:
        return f.read()


setup(
    name='zedenv-grub',
    version='0.0.0',
    description='zedenv Plugin for GRUB',
    url='http://github.com/johnramsden/zedenv',
    author='John Ramsden',
    author_email='johnramsden@riseup.net',
    license='BSD-3-Clause',
    classifiers=[
      'Development Status :: 3 - Pre Alpha',
      'License :: OSI Approved :: BSD License',
      'Programming Language :: Python :: 3.6',
      'Programming Language :: Python :: 3.7',
    ],
    keywords='cli',
    packages=find_packages(exclude=["*tests*", "test_*"]),
    install_requires=['click', 'zedenv'],
    setup_requires=['pytest-runner'],
    tests_require=tests_require,
    extras_require={
        'test': tests_require,
        'dev': dev_require,
    },
    entry_points="""
        [zedenv.plugins]
        grub = zedenv_grub.grub:GRUB
    """,
    zip_safe=False,
    data_files=[("/etc/grub.d", ["grub.d/05_zfs_linux.py"])],
)
