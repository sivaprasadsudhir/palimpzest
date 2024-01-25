import palimpzest as pz

class ScientificPaper(pz.File):
   """Represents a scientific research paper, which in practice is usually from a PDF file"""
   title = pz.Field(desc="The title of the paper. This is a natural language title, not a number or letter.", required=True)
   publicationYear = pz.Field(desc="The year the paper was published. This is a number.", required=False)

def getMITBatteryPapers():
    #
    # A dataset-independent declarative description of authors of good papers
    #
    sciPapers = pz.Set(ScientificPaper) # This is a formal paper description.
    mitPapers = sciPapers.addFilterStr("The paper is from MIT")
    batteryPapers = mitPapers.addFilterStr("The paper is about batteries")
    goodAuthorPapers = batteryPapers.addFilterStr("Papers where the author list contains at least one highly-respected author",
                                            targetFn=lambda x: x.authors)

    # Now we configure it for a particular runtime environment. We indicate:
    # 1) Data sources for  elements
    # 2) Labeled example repositories to check
    # 3) Runtime options
    #processor = pz.Processor(rootElement=goodAuthorPapers,
    #                         populatedElements=[(sciPapers, pz.DirectorySource("./testFileDirectory"))],
    #                         exampleRepos = ["http://goodexamples.com", "./localexamples.csv"],
    #                         streaming=False)

    # Compiling the pipeline means that we can now execute it.
    # It entails:
    # 1) Making sure all leaf elements have a data source
    # 2) Applying any runtime optimizations (e.g. reordering and pushing predicates down)
    # 3) Figuring out the type conversions needed in every step
    # 4) Marshalling examples for each type conversion. These are ideally sensitive to the input data source.
    # 5) Synthesizing markup tools for each step in the plan, in case the user wants to manually annotate the data.
    # 6) Synthesizing the executable steps and compiling them into a runtime plan.
    #compileStats = processor.compile()

    # Pretty print the compileStats dict
    #print("CompileStats:")
    #for k, v in compileStats.items():
    #    print(f"  {k}: {v}")


    #print()
    #print("Logical tree:")
    #processor.dumpLogicalTree()

    def emitNestedTuple(node, indent=0):
        elt, child = node
        print(" " * indent, elt)
        if child is not None:
            emitNestedTuple(child, indent=indent+2)

    print()
    print("Syntactic operator tree:")
    syntacticElements = goodAuthorPapers.dumpSyntacticTree()
    emitNestedTuple(syntacticElements)

    print()
    print("Logical operator tree:")
    logicalTree = goodAuthorPapers.getLogicalTree()
    logicalElements = logicalTree.dumpLogicalTree()
    emitNestedTuple(logicalElements)

    jsonSchema = logicalTree.outputElementType.jsonSchema()
    jsonSchema["title"]="Good MIT battery papers written by good authors"
    print()
    print("JSON SCHEMA")
    # Convert the dict to a string and print it
    import json
    print(json.dumps(jsonSchema, indent=2))


    physicalTree = logicalTree.getPhysicalTree()

    dataSrc = pz.DirectorySource("./testFileDirectory")
    physicalTree.finalize(dataSrc)
    print(physicalTree)

    print()

    #iterate oer directory source
    for f in dataSrc:
        print(f)

    #
    # FUTURE WORK
    #

    # Indicate that the author must have an ORCID, which matches the ORCID database

    # (Or, in a different setting: indicate that the git commit must contain a URL that points to a valid git repo)

    # (Or, in a different setting: indicate that the gene must be drawn from a standard list of genes)



    # This section is the actual execution. It executes the above runtime plan
    #
    # This will run compile() if it hasn't been run already, if the code has changed, or if 
    # there are new labeled examples to exploit.
    #
    # If you want to avoid reoptimizing with the new examples, you can instead run "execute(reoptimize=False)"
    # But if the code has changed since the last compile, we *always* recompile.
    #
    # Executing the pipeline always deposits statistics in the metadata directory and returns a pointer to them.
    # It does not write to disk the data itself unless you've set that flag.
    # The result data are available via Element.data

    #TODO -- michjc
    #executionStats = processor.execute()

    #for a in processor.resultElement.data:
    #    print(a)

    #print("This is what I executed:")
    #print(executionStats.compileStats.plan)
    #print()
    #print("It took this long:", executionStats.runtimeStats.elapsedTime)

##
# What does the compiler do?
#It:
#1. Iterates through all elements returned by the datasource.
#2. Tests each element to see if it is an example of `scientificPaper`
#3.  ... which means testing to see if it is a datatype that is a superclass of ScientificPaper
#4.  ... and whether it "Represents a scientfic reseach paper, usually from a PDF file"
#5.  ... and whether it contains all the required fields described by ScientificPaper.
#

getMITBatteryPapers()

