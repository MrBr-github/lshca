from setuptools import setup

from os import path
this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
  name = 'lshca',
  packages = ['lshca'],
  version = '3.6',
  license='GNU GPLv3',
  description = 'This utility comes to provide bird\'s-eye view of HCAs installed',
  long_description=long_description,
  long_description_content_type='text/markdown',
  author = 'Michael Braverman',
  author_email = 'mrbr.mail@gmail.com',
  url = 'https://github.com/MrBr-github/lshca',
  download_url = 'https://github.com/MrBr-github/lshca/archive/v3.6.tar.gz',
  keywords = ['HCA', 'INFINIBAND', 'ROCE'],
#  install_requires=[  '', '', ],
  classifiers=[
    'Development Status :: 5 - Production/Stable',
    'Intended Audience :: System Administrators',
    'Intended Audience :: Information Technology',
    'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
    'Programming Language :: Python :: 2.7',
    'Programming Language :: Python :: 3'
  ],
  entry_points={
    'console_scripts': [
      'lshca=lshca:main',
    ],
  }
)
