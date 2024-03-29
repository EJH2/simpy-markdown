import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="simpy_markdown",
    version="0.0.3",
    author="EJH2",
    description="simple-markdown, but Python",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/EJH2/simpy-markdown",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.8',
)
