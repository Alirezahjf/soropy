from setuptools import setup, find_packages

setup(
    name="soropy",
    version="1.2.0",
    packages=find_packages(),
    install_requires=[
        "selenium>=4.10.0",
    ],
    extras_require={
        "ws": [
            "splusthon>=1.1.0",
            "aiohttp>=3.8.0",
            "pyaes>=1.6.1",
            "rsa>=4.0",
        ],
        "all": [
            "splusthon>=1.1.0",
            "aiohttp>=3.8.0",
            "pyaes>=1.6.1",
            "rsa>=4.0",
        ],
    },
    python_requires=">=3.8",
    author="SoroPy Team",
    description="Professional Soroush Plus Web Client Library for Python",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/soropy/soropy",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)