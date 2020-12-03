from setuptools import setup
setup(
  name = 'lshca',
  packages = ['lshca'],
  version = '3.3.2',
  license='GNU GPLv3',
  description = 'This utility comes to provide bird\'s-eye view of HCAs installed',
  author = 'Michael Braverman',
  author_email = 'mrbr.mail@gmail.com',
  url = 'https://github.com/MrBr-github/lshca',
  download_url = 'https://github.com/MrBr-github/lshca/archive/v3.3.tar.gz',
  keywords = ['HCA', 'INFINIBAND'],
#  install_requires=[  '', '', ],
  classifiers=[
    'Development Status :: 5 - Production/Stable',
    'Intended Audience :: System Administrators', 
    'Intended Audience :: Information Technology',
    'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
    'Programming Language :: Python :: 2.7'      
  ],
  entry_points={
    'console_scripts': [
      'lshca=lshca:main',
    ],
  }
)
