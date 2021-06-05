from setuptools import setup, find_packages


setup(
    name="broca-framework",
    version="0.0.1",
    description="A dialogue system framework",
    author="Rossi",
    packages=find_packages(exclude=("test", "test.*", "data")),
    include_package_data = True,
    data_files = [("resource", ["resource/templates/simple/intent_patterns.json", 
                   "resource/templates/simple/faq_agent/faq_agent_config.json"])],
    entry_points = {  
        'console_scripts': [  
             'broca = Broca.__main__:main'  
         ]  
    }
)
