from setuptools import setup
setup(
  name = 'lshca',
  packages = ['lshca'],
  version = '4.0-rc1',
  license='GNU GPLv3',
  description = 'This utility and library comes to provide bird\'s-eye view of HCAs installed',
  author = 'Michael Braverman',
  author_email = 'mrbr.mail@gmail.com',
  url = 'https://github.com/MrBr-github/lshca',
  download_url = 'https://github.com/MrBr-github/lshca/archive/v4.0.tar.gz',
  keywords = ['HCA', 'INFINIBAND'],
#  install_requires=[  '', '', ],
  classifiers=[
    'Development Status :: 3 - Alpha',
    'Intended Audience :: System Administrators', 
    'Intended Audience :: Information Technology',
    'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
    'Programming Language :: Python :: 2.7',      
    'Programming Language :: Python :: 3'      
  ],
  entry_points={
    'console_scripts': [
      'lshca=lshca.cli:main',
    ],
  }
)
