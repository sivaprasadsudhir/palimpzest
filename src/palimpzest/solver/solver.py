from palimpzest.constants import Model, PromptStrategy, QueryStrategy
from palimpzest.elements import DataRecord, EquationImage, File, Filter, ImageFile, PDFFile, Schema, TextFile
from palimpzest.generators import DSPyGenerator, describe_image, run_cot_bool, run_cot_qa, gen_filter_signature_class, gen_qa_signature_class
from palimpzest.solver import runBondedQuery, runConventionalQuery
from palimpzest.tools.pdfparser import get_text_from_pdf
from palimpzest.tools.skema_tools import equations_to_latex

from dataclasses import dataclass
from papermage import Document

import json
import modal


@dataclass
class TaskDescriptor:
    """Dataclass for describing tasks sent to the Solver."""
    # the name of the physical operation in need of a function from the solver
    physical_op: str
    # the input schema
    inputSchema: Schema
    # the output schema
    outputSchema: Schema = None
    # the operation id
    op_id: str = None
    # the model to use in the task
    model: Model = None
    # the prompt strategy
    prompt_strategy: PromptStrategy = None
    # the query strategy
    query_strategy: QueryStrategy = None
    # the filter for filter operations
    filter: Filter = None
    # the optional description of the conversion being applied (if task is a conversion)
    conversionDesc: str = None
    # name of the pdfprocessing tool to use (if applicable)
    pdfprocessor: str = None

    def __str__(self) -> str:
        """Use the __repr__() function which is automagically implemented by @dataclass"""
        return self.__repr__()


class Solver:
    """
    This class exposes a synthesize() method, which takes in a physical operator's
    high-level description of a task to be performed (e.g. to convert a record between
    two schemas, or to filter records adhering to a specific schema) and returns a
    function which executes that task.

    The functions returned by the Solver are responsible for marshalling input records
    and producing valid output records (where "validity" is task-specific).
    
    These functions are NOT responsible for managing the details of LLM output generation.
    That responsibility lies in the Generator class(es).

    TODO: I think the abstraction between Solver and Generator is improved, but I'm still
          not sure if it makes sense for the Solver to handle the construction of the context
          and question which are ultimately passed into the Generator?
    
    TODO: the solver should not do things which the physical operator cannot estimate the cost of,
          e.g., in the world in which we have bonded queries, llm generated code, and conventional queries,
          these behaviors all need to be dictated by the TaskDescriptor (which should become a dataclass);
          the physical operator is in charge of sending the TaskDescriptor to the Solver, which then
          formulaically creates the task function in accordance w/the given TaskDescriptor
    """
    def __init__(self, verbose: bool=False):
        self._hardcodedFns = {}
        self._simpleTypeConversions = set()
        self._hardcodedFns = set()
        self._hardcodedFns.add((PDFFile, File))
        self._hardcodedFns.add((PDFFile, File))
        self._hardcodedFns.add((TextFile, File))
        # self._hardcodedFns.add((ImageFile, File))
        # self._hardcodedFns.add((EquationImage, ImageFile))
        self._verbose = verbose

    def easyConversionAvailable(self, outputSchema: Schema, inputSchema: Schema):
        return (outputSchema, inputSchema) in self._simpleTypeConversions or (outputSchema, inputSchema) in self._hardcodedFns

    def _makeSimpleTypeConversionFn(self, td: TaskDescriptor):
        """This is a very simple function that converts a DataRecord from one Schema to another, when we know they have identical fields."""
        def _simpleTypeConversionFn(candidate: DataRecord):
            if not candidate.schema == td.inputSchema: # TODO: stats?
                return None

            dr = DataRecord(td.outputSchema)
            for field in td.outputSchema.fieldNames():
                if hasattr(candidate, field):
                    setattr(dr, field, getattr(candidate, field))
                elif field.required:
                    return None
            return dr
        return _simpleTypeConversionFn

    def _makeHardCodedTypeConversionFn(self, td: TaskDescriptor, shouldProfile: bool=False):
        """This converts from one type to another when we have a hard-coded method for doing so."""
        if td.outputSchema == PDFFile and td.inputSchema == File: # TODO: stats?
            if td.pdfprocessor == "modal":
                print("handling PDF processing remotely")
                remoteFunc = modal.Function.lookup("palimpzest.tools", "processPapermagePdf")
            else:
                remoteFunc = None
                
            def _fileToPDF(candidate: DataRecord):
                pdf_bytes = candidate.contents
                pdf_filename = candidate.filename
                if remoteFunc is not None:
                    docJsonStr = remoteFunc.remote([pdf_bytes])
                    docdict = json.loads(docJsonStr[0])
                    doc = Document.from_json(docdict)
                    text_content = ""
                    for p in doc.pages:
                        text_content += p.text
                else:
                    text_content = get_text_from_pdf(candidate.filename, candidate.contents)
                dr = DataRecord(td.outputSchema)
                dr.filename = pdf_filename
                dr.contents = pdf_bytes
                dr.text_contents = text_content
                return dr
            return _fileToPDF
        elif td.outputSchema == TextFile and td.inputSchema == File: # TODO: stats?
            def _fileToText(candidate: DataRecord):
                if not candidate.schema == td.inputSchema:
                    return None
                text_content = str(candidate.contents, 'utf-8')
                dr = DataRecord(td.outputSchema)
                dr.filename = candidate.filename
                dr.contents = text_content
                return dr
            return _fileToText
        elif td.outputSchema == EquationImage and td.inputSchema == ImageFile:
            print("handling image to equation through skema")
            def _imageToEquation(candidate: DataRecord):
                if not candidate.element == td.inputSchema:
                    return None

                dr = DataRecord(td.outputSchema)
                dr.filename = candidate.filename
                dr.contents = candidate.contents
                dr.equation_text, stats = equations_to_latex(candidate.contents)
                print("Running equations_to_latex_base64: ", dr.equation_text)
                # if profiling, set record's stats for the given op_id
                if shouldProfile:
                    dr._stats[td.op_id] = stats
                return dr
            return _imageToEquation
        else:
            raise Exception(f"Cannot hard-code conversion from {td.inputSchema} to {td.outputSchema}")

    def _makeLLMTypeConversionFn(self, td: TaskDescriptor, shouldProfile: bool=False):
        def fn(candidate: DataRecord):
            # ask LLM to generate all empty fields in the outputSchema; if a field in the
            # outputSchema already exists in the inputSchema, we copy the value
            stats = {"bondedQuery": None, "conventionalQuery": None}

            if td.query_strategy == QueryStrategy.CONVENTIONAL:
                # NOTE: runConventionalQuery does exception handling internally
                dr, conventional_query_stats = runConventionalQuery(candidate, td, self._verbose)

                # if profiling, set record's stats for the given op_id
                if shouldProfile:
                    stats["conventionalQuery"] = conventional_query_stats
                    dr._stats[td.op_id] = stats

                return dr

            elif td.query_strategy == QueryStrategy.BONDED:
                dr, bonded_query_stats, err_msg = runBondedQuery(candidate, td, self._verbose)

                # if bonded query failed, manually set fields to None
                if err_msg is not None:
                    print(f"BondedQuery Error: {err_msg}")
                    dr = DataRecord(td.outputSchema)
                    for field_name in td.outputSchema.fieldNames():
                        setattr(dr, field_name, None)

                # if profiling, set record's stats for the given op_id
                if shouldProfile:
                    stats["bondedQuery"] = bonded_query_stats
                    dr._stats[td.op_id] = stats

                return dr
                
            elif td.query_strategy == QueryStrategy.BONDED_WITH_FALLBACK:
                dr, bonded_query_stats, err_msg = runBondedQuery(candidate, td, self._verbose)

                # if bonded query failed, run conventional query
                if err_msg is not None:
                    print(f"BondedQuery Error: {err_msg}")
                    print("Falling back to conventional query")
                    dr, conventional_query_stats = runConventionalQuery(candidate, td, self._verbose)

                    # if profiling, set conventional query stats
                    if shouldProfile:
                        stats["conventionalQuery"] = conventional_query_stats

                # if profiling, set record's stats for the given op_id
                if shouldProfile:
                    stats["bondedQuery"] = bonded_query_stats
                    dr._stats[td.op_id] = stats

                return dr

            # TODO
            elif td.query_strategy == QueryStrategy.CODE_GEN:
                raise Exception("not implemented yet")

            # TODO
            elif td.query_strategy == QueryStrategy.CODE_GEN_WITH_FALLBACK:
                raise Exception("not implemented yet")

            else:
                raise ValueError(f"Unrecognized QueryStrategy: {td.query_strategy.value}")

        return fn

    def _makeFilterFn(self, td: TaskDescriptor, shouldProfile: bool=False):
            # compute record schema and type
            doc_schema = str(td.inputSchema)
            doc_type = td.inputSchema.className()

            # By default, a filter requires an LLM invocation to run
            # Someday maybe we will offer the user the chance to run a hard-coded function.
            # Or maybe we will ask the LLM to synthesize traditional code here.
            def createLLMFilter(filterCondition: str):
                def llmFilter(candidate: DataRecord):
                    # do not filter candidate if it doesn't match inputSchema
                    if not candidate.schema == td.inputSchema:
                        return False

                    # create generator
                    generator = None
                    if td.prompt_strategy == PromptStrategy.DSPY_COT_BOOL:
                        generator = DSPyGenerator(td.model.value, td.prompt_strategy, doc_schema, doc_type, self._verbose)
                    # TODO
                    elif td.prompt_strategy == PromptStrategy.ZERO_SHOT:
                        raise Exception("not implemented yet")
                    # TODO
                    elif td.prompt_strategy == PromptStrategy.FEW_SHOT:
                        raise Exception("not implemented yet")
                    # TODO
                    elif td.prompt_strategy == PromptStrategy.CODE_GEN_BOOL:
                        raise Exception("not implemented yet")

                    # invoke LLM to generate filter decision (True or False)
                    text_content = candidate.asTextJSON()
                    response, stats = generator.generate(context=text_content, question=filterCondition)

                    # if profiling, set record's stats for the given op_id
                    if shouldProfile:
                        candidate._stats[td.op_id] = stats

                    # set _passed_filter attribute and return record
                    setattr(candidate, "_passed_filter", response.lower() == "true")

                    return candidate

                return llmFilter
            return createLLMFilter(str(td.filter))

    def synthesize(self, taskDescriptor: TaskDescriptor, shouldProfile: bool=False):
        """
        Return a function that implements the desired task as specified by some PhysicalOp.
        Right now, the two primary tasks that the Solver provides solutions for are:

        1. Induce operations
        2. Filter operations

        The shouldProfile parameter also determines whether or not PZ should compute
        profiling statistics for LLM invocations and attach them to each record.
        """
        # synthesize a function to induce from inputType to outputType
        if "InduceFromCandidateOp" in taskDescriptor.physical_op:
            typeConversionDescriptor = (taskDescriptor.outputSchema, taskDescriptor.inputSchema)
            if typeConversionDescriptor in self._simpleTypeConversions:
                return self._makeSimpleTypeConversionFn(taskDescriptor)
            elif typeConversionDescriptor in self._hardcodedFns:
                return self._makeHardCodedTypeConversionFn(taskDescriptor, shouldProfile)
            else:
                return self._makeLLMTypeConversionFn(taskDescriptor, shouldProfile)

        # synthesize a function to filter records
        elif "FilterCandidateOp" in taskDescriptor.physical_op:
            return self._makeFilterFn(taskDescriptor, shouldProfile)

        else:
            raise Exception("Cannot synthesize function for task descriptor: " + str(taskDescriptor))
