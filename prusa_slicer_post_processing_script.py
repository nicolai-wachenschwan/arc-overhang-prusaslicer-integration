"""
This script generates Overhangs by stringing together Arcs, allowing successful fdm-3d-printing of large 90 deg overhangs!
The genius Idea is emerged from Steven McCulloch, who coded a demonstration and the basic mechanics: https://github.com/stmcculloch/arc-overhang
This python script builds up on that and offers a convinient way to integrate the ArcOverhangs into an existing gcode-file.
HOW TO USE: 
Option A) open your system console and type 'python ' followed by the path to this script and the path of the gcode file. Will overwrite the file.
Option B) open PrusaSlicer, go to print-settings-tab->output-options. Locate the window for post-processing-script. 
    In that window enter: full path to your python exe,emtyspace, full path to this script.
    If the python path contains any empty spaces, mask them as described here: https://manual.slic3r.org/advanced/post-processing
=>PrusaSlicer will execute the script after the export of the Gcode, therefore the view in the window wont change. Open the finished gcode file to see the results.
If you want to change generation settings: Scroll to 'Parameter' section. Settings from PrusaSlicer will be extracted automaticly from the gcode.
Requirements:
Python 3.5+ and the librarys: shapely 1.8+, numpy 1.2+, numpy-hilbert-curve matplotlib for debugging
Slicing in PrusaSlicer is mandatory.
Tested only in PrusaSlicer 2.5&Python 3.10, other versions might need adapted keywords.
Notes:
This code is a little messy. Usually I would devide it into multiple files, but that would compromise the ease of use.
Therefore I divided the code into sections, marked with ###
Feel free to give it some refactoring and add more functionalities!
Used Coding-Flavour: variable Names: smallStartEveryWordCapitalized, 'to' replaced by '2', same for "for"->"4". Parameters: BigStartEveryWordCapitalized
Known issues:
-pointsPerCircle>80 might give weird results
-MaxDistanceFromPerimeter >=2*perimeterwidth might weird result.
-avoid using the code multiple times onto the same gcode, since the bridge infill is deleted when the arcs are generated.
"""
#!/usr/bin/python
import sys
import os
from shapely import Point, Polygon, LineString, GeometryCollection, MultiLineString, MultiPolygon
from shapely.ops import nearest_points
from shapely.ops import linemerge, unary_union
import matplotlib.pyplot as plt
import numpy as np
from ast import literal_eval
import warnings
import random
import platform
#from hilbertcurve.hilbertcurve import HilbertCurve
from hilbert import decode, encode
import argparse
########## Parameters  - adjust values here as needed ##########
def makeFullSettingDict(gCodeSettingDict:dict) -> dict: 
    """Merge Two Dictionarys and set some keys/values explicitly"""
    #the slicer-settings will be imported from GCode. But some are Arc-specific and need to be adapted by you.
    AddManualSettingsDict={
        #adapt these settings as needed for your specific geometry/printer:
        "CheckForAllowedSpace":False,# use the following x&y filter or not
        "AllowedSpaceForArcs": Polygon([[0,0],[500,0],[500,500],[0,500]]),#have control in which areas Arcs shall be generated
        "ArcCenterOffset":2, # Unit:mm, prevents very small Arcs by hiding the center in not printed section. Make 0 to get into tricky spots with smaller arcs.
        "ArcMinPrintSpeed":0.5*60,#Unit:mm/min
        "ArcPrintSpeed":1.5*60, #Unit:mm/min
        #"ArcPrintTemp":gCodeSettingDict.get("temperature"), # unit: Celsius
        "ArcTravelFeedRate":30*60, # slower travel speed, Unit:mm/min
        "ExtendIntoPerimeter":1.5*gCodeSettingDict.get("perimeter_extrusion_width"), #min=0.5extrusionwidth!, extends the Area for arc generation, put higher to go through small passages. Unit:mm
        "MaxDistanceFromPerimeter":2*gCodeSettingDict.get("perimeter_extrusion_width"),#Control how much bumpiness you allow between arcs and perimeter. lower will follow perimeter better, but create a lot of very small arcs. Should be more that 1 Arcwidth! Unit:mm
        "MinArea":5*10,#Unit:mm2
        "MinBridgeLength":5,#Unit:mm
        "Path2Output":r"", #leave empty to overwrite the file or write to a new file. Full path required.
        "RMax":110, # the max radius of the arcs.
        "TimeLapseEveryNArcs": 0, #deactivate with 0, inserts M240 after N ArcLines, 5 is a good value to start.

        #Special cooling to prevent warping:
        "aboveArcsFanSpeed":25, #0->255, 255=100%
        "aboveArcsInfillPrintSpeed":10*60, # Unit :mm/min
        "aboveArcsPerimeterFanSpeed":25, #0->255, 255=100%
        "aboveArcsPerimeterPrintSpeed":3*60, #Unit: mm/min
        "applyAboveFanSpeedToWholeLayer":True,
        "CoolingSettingDetectionDistance":5, #if the gcode line is closer than this distance to an infill polygon the cooling settings will be applied. Unit:mm
        "specialCoolingZdist":3, #use the special cooling XX mm above the arcs.

        #advanced Settings, you should not need to touch these.
        "ArcExtrusionMultiplier":1.35,
        "ArcSlowDownBelowThisDuration":3,# Arc Time below this Duration =>slow down, Unit: sec
        "ArcWidth":gCodeSettingDict.get("nozzle_diameter")*0.95, #change the spacing between the arcs,should be nozzle_diameter
        "ArcFanSpeed":255,#cooling to full blast=255
        "CornerImportanceMultiplier":0.2, # Startpoint for Arc generation is chosen close to the middle of the StartLineString and at a corner. Higher=>Cornerselection more important.
        "DistanceBetweenPointsOnStartLine":0.1,#used for redestribution, if start fails.
        "GCodeArcPtMinDist":0.1, # min Distance between points on the Arcs to for seperate GCode Command. Unit:mm
        "ExtendArcDist":1.0, # extend Arcs tangentially for better bonding bewteen them, only end-piece affected(yet), Unit:mm
        "HilbertFillingPercentage":100, # infillpercentage of the massive layers with special cooling. Uses Hilbert Curve, works not quite right yet.
        "HilbertInfillExtrusionMultiplier":1.05, 
        "HilbertTravelEveryNSeconds":6, # when N seconds are driven it will continue printing somewhere else (very rough approx).
        "MinStartArcs":2, # how many arcs shall be generated in first step
        "PointsPerCircle":80, # each Arc starts as a discretized circle. Higher will slow down the code but give more accurate results for the arc-endings. 
        "SafetyBreak_MaxArcNumber":2000, #max Number of Arc Start Points. prevents While loop form running for ever.
        "WarnBelowThisFillingPercentage":90, # fill the overhang at least XX%, else send a warning. Easier detection of errors in small/delicate areas. Unit:Percent
        "UseLeastAmountOfCenterPoints":True, # always generates arcs until rMax is reached, divide the arcs into pieces in needed. reduces the amount of centerpoints.
    
        #settings for easier debugging:
        "plotStart":False, # plot the detected geoemtry in the prev Layer and the StartLine for Arc-Generation, use for debugging
        "plotArcsEachStep":False, #plot arcs for every filled polygon. use for debugging
        "plotArcsFinal":False, #plot arcs for every filled polygon, when completely filled. use for debugging
        "plotDetectedInfillPoly":False, # plot each detected overhang polygon, use for debugging.
        "plotEachHilbert":False,
        "PrintDebugVerification":False
        }
    gCodeSettingDict.update(AddManualSettingsDict)
    return gCodeSettingDict

################################# MAIN FUNCTION #################################
#################################################################################    
#at the top, for better reading
def main(gCodeFileStream,path2GCode,skipInput)->None:
    '''Here all the work is done, therefore it is much to long.'''
    gCodeLines=gCodeFileStream.readlines()
    gCodeSettingDict=readSettingsFromGCode2dict(gCodeLines,{"Fallback_nozzle_diameter":0.4,"Fallback_filament_diameter":1.75}) #ADD FALLBACK VALUES HERE
    parameters=makeFullSettingDict(gCodeSettingDict)
    if not checkforNecesarrySettings(gCodeSettingDict):
        warnings.warn("Incompatible PursaSlicer-Settings used!")
        input("Can not run script, gcode unmodified. Press enter to close.")
        raise ValueError("Incompatible Settings used!") 
    layerobjs=[]
    gcodeWasModified=False
    if gCodeFileStream:
        layers=splitGCodeIntoLayers(gCodeLines)
        gCodeFileStream.close()
        print("layers:",len(layers))
        lastfansetting=0 # initialize variable
        for idl,layerlines in enumerate(layers):
            layer=Layer(layerlines,parameters,idl)
            layer.addZ()
            layer.addHeight()
            lastfansetting=layer.spotFanSetting(lastfansetting)
            layerobjs.append(layer)   
        for idl,layer in enumerate(layerobjs):
            modify=False 
            if idl<1:
                continue # no overhangs in the first layer and dont mess with the setup
            else:
                layer.extract_features()
                layer.spotBridgeInfill()
                layer.makePolysFromBridgeInfill(extend=parameters.get("ExtendIntoPerimeter",1))
                layer.polys=layer.mergePolys()
                layer.verifyinfillpolys()    

                #ARC GENERATION
                if layer.validpolys:
                    modify=True
                    gcodeWasModified=True
                    print(f"overhang found layer {idl}:",len(layer.polys), f"Z: {layer.z:.2f}")
                    #set special cooling settings for the follow up layers
                    maxZ=layer.z+parameters.get("specialCoolingZdist")
                    idoffset=1
                    currZ=layer.z
                    while currZ<=maxZ and idl+idoffset<=len(layerobjs)-1:
                        currZ=layerobjs[idl+idoffset].z
                        layerobjs[idl+idoffset].oldpolys.extend(layer.validpolys)
                        idoffset+=1

                    #make Startpoint form previous layer    
                    prevLayer=layerobjs[idl-1]
                    prevLayer.makeExternalPerimeter2Polys()
                    arcOverhangGCode=[]  
                    for poly in layer.validpolys:
                        #make parameters more readable
                        MaxDistanceFromPerimeter=parameters.get("MaxDistanceFromPerimeter") # how much 'bumpiness' you accept in the outline. Lower will generate more small arcs to follow the perimeter better (corners!). Good practice: 2 perimeters+ threshold of 2width=minimal exact touching (if rMin satisfied)
                        rMax=parameters.get("RMax",15)
                        pointsPerCircle=parameters.get("PointsPerCircle",80)
                        arcWidth=parameters.get("ArcWidth")
                        rMin=parameters.get("ArcCenterOffset")+arcWidth/1.5
                        rMinStart=parameters.get("nozzle_diameter")
                        #initialize
                        finalarcs=[]
                        arcs=[]
                        arcs4gcode=[]
                        #find StartPoint and StartLineString
                        startLineString,boundaryWithOutStartLine=prevLayer.makeStartLineString(poly,parameters)
                        if startLineString is None:
                            warnings.warn("Skipping Polygon because no StartLine Found")
                            continue
                        startpt=getStartPtOnLS(startLineString,parameters)
                        remainingSpace=poly
                        #plot_geometry(thresholdedpoly)
                        #plot_geometry(startLineString,'m')
                        #plot_geometry(startpt,'r')
                        #plt.axis('square')
                        #plt.show()
                        #first step in Arc Generation
                        
                        concentricArcs=generateMultipleConcentricArcs(startpt,rMinStart,rMax,boundaryWithOutStartLine,remainingSpace,parameters)
                        #print(f"number of concentric arcs generated:",len(concentricArcs))
                        if len(concentricArcs)<parameters.get("MinStartArcs"): 
                            #possibly bad chosen startpt, errorhandling:
                            startpt=getStartPtOnLS(redistribute_vertices(startLineString,0.1),parameters)
                            concentricArcs=generateMultipleConcentricArcs(startpt,rMinStart,rMax,boundaryWithOutStartLine,remainingSpace,parameters)
                            if len(concentricArcs)<parameters.get("MinStartArcs"):#still insuff start: try random
                                print(f"Layer {idl}: Using random Startpoint")
                                for idr in range(10):
                                    startpt=getStartPtOnLS(startLineString,parameters,choseRandom=True)
                                    concentricArcs=generateMultipleConcentricArcs(startpt,rMinStart,rMax,boundaryWithOutStartLine,remainingSpace,parameters)
                                    if len(concentricArcs)>=parameters.get("MinStartArcs"):
                                        break
                                if len(concentricArcs)<parameters.get("MinStartArcs"):    
                                    for idr in range(10):
                                        startpt=getStartPtOnLS(redistribute_vertices(startLineString,0.1),parameters,choseRandom=True)
                                        concentricArcs=generateMultipleConcentricArcs(startpt,rMinStart,rMax,boundaryWithOutStartLine,remainingSpace,parameters)    
                                        if len(concentricArcs)>=parameters.get("MinStartArcs"):
                                            break              
                                if len(concentricArcs)<parameters.get("MinStartArcs"):        
                                    warnings.warn("Initialization Error: no concentric Arc could be generated at startpoints, moving on")
                                    continue
                        arcBoundarys=getArcBoundarys(concentricArcs)
                        finalarcs.append(concentricArcs[-1]) 
                        for arc in concentricArcs: 
                            remainingSpace=remainingSpace.difference(arc.poly.buffer(1e-2))
                            arcs.append(arc)
                        for arcboundary in arcBoundarys:    
                            arcs4gcode.append(arcboundary)
  
                        #start bfs (breadth first search algorithm) to fill the remainingspace
                        idx=0
                        safetyBreak=0
                        triedFixing=False
                        while idx<len(finalarcs):
                            sys.stdout.write("\033[F") #back to previous line 
                            sys.stdout.write("\033[K") #clear line 
                            print("while executed:",idx, len(finalarcs))#\r=Cursor at linestart
                            curArc=finalarcs[idx]
                            if curArc.poly.geom_type=="MultiPolygon":
                                farthestPointOnArc,longestDistance,NearestPointOnPoly=get_farthest_point(curArc.poly.geoms[0],poly,remainingSpace)
                            else:
                                farthestPointOnArc,longestDistance,NearestPointOnPoly=get_farthest_point(curArc.poly,poly,remainingSpace)
                            if not farthestPointOnArc or longestDistance<MaxDistanceFromPerimeter:#no more pts on arc
                                idx+=1 #go to next arc
                                continue
                            startpt=move_toward_point(farthestPointOnArc,curArc.center,parameters.get("ArcCenterOffset",2))
                            concentricArcs=generateMultipleConcentricArcs(startpt,rMin,rMax,poly.boundary,remainingSpace,parameters)
                            arcBoundarys=getArcBoundarys(concentricArcs)
                            #print(f"number of concentric arcs generated:",len(concentricArcs))
                            if len(concentricArcs)>0:
                                for arc in concentricArcs: 
                                    remainingSpace=remainingSpace.difference(arc.poly.buffer(1e-2))
                                    arcs.append(arc)
                                finalarcs.append(concentricArcs[-1])
                                for arcboundary in arcBoundarys:    
                                    arcs4gcode.append(arcboundary)
                            else:
                                idx+=1 # no possible concentric arcs found= arc complete, proceed to next
                            safetyBreak+=1
                            if safetyBreak>parameters.get("SafetyBreak_MaxArcNumber",2000):
                                break
                            if parameters.get("plotArcsEachStep"):
                                plt.title(f"Iteration {idx}, Total No Start Points: {len(finalarcs)}, Total No Arcs: {len(arcs)}")
                                plot_geometry(startLineString,'r')
                                plot_geometry([arc.poly for arc in arcs],changecolor=True)
                                plot_geometry(remainingSpace,'g',filled=True)
                                plot_geometry(startpt,"r")
                                plt.axis('square')
                                plt.show()
                                
                            if len(finalarcs)==1 and idx==1 and remainingSpace.area/poly.area*100>50 and not triedFixing:
                                #error handling: the arc-generation got stuck at a thight spot during startup. Automated fix:
                                parameters["ArcCenterOffset"]=0
                                rMin=arcWidth/1.5
                                idx=0
                                triedFixing=True
                                print("the arc-generation got stuck at a thight spot during startup. Used Automated fix:set ArcCenterOffset to 0")
                            if triedFixing and len(finalarcs)==1 and idx==1:
                                print("fix did not work.")    
                        #poly finished
                        remain2FillPercent=remainingSpace.area/poly.area*100
                        if  remain2FillPercent> 100-parameters.get("WarnBelowThisFillingPercentage"):
                            warnings.warn(f"layer {idl}: The Overhang Area is only {100-remain2FillPercent:.0f}% filled with Arcs. Please try again with adapted Parameters: set 'ExtendIntoPerimeter' higher to enlargen small areas. lower the MaxDistanceFromPerimeter to follow the curvature more precise. Set 'ArcCenterOffset' to 0 to reach delicate areas. ")                 
                        if parameters.get("plotArcsFinal"):
                            plt.title(f"Iteration {idx}, Total No Start Points: {len(finalarcs)}, Total No Arcs: {len(arcs)}")
                            plot_geometry(startLineString,'r')
                            plot_geometry([arc.poly for arc in arcs],changecolor=True)
                            plot_geometry(remainingSpace,'g',filled=True)
                            plot_geometry(startpt,"r")
                            plt.axis('square')
                            plt.show()  
                        #generate gcode for arc and insert at the beginning of the layer
                        eStepsPerMM=calcEStepsPerMM(parameters)
                        arcOverhangGCode.append(f"M106 S{np.round(parameters.get('bridge_fan_speed',100)*2.55)}\n")#turn cooling Fan on at Bridge Setting
                        #for arc in arcs4gcode:
                        #    plot_geometry(arc)
                        #    plot_geometry(Point(arc.coords[0]))
                        #plt.axis('square')
                        #plt.show()
                        for ida,arc in enumerate(arcs4gcode):
                            if not arc.is_empty:    
                                arcGCode=arc2GCode(arcline=arc,eStepsPerMM=eStepsPerMM,arcidx=ida,kwargs=parameters)
                                arcOverhangGCode.append(arcGCode)
                                if parameters.get("TimeLapseEveryNArcs")>0:
                                    if ida%parameters.get("TimeLapseEveryNArcs"):
                                        arcOverhangGCode.append("M240\n")

                #apply special cooling settings:    
                if len(layer.oldpolys)>0:
                    modify=True
                    print("oldpolys found in layer:",idl)
                    layer.spotSolidInfill()
                    layer.makePolysFromSolidInfill(extend=parameters.get("ExtendIntoPerimeter"))
                    layer.solidPolys=layer.mergePolys(layer.solidPolys)
                    allhilbertpts=[]
                    for poly in layer.solidPolys:
                        hilbertpts=layer.createHilbertCurveInPoly(poly)
                        allhilbertpts.extend(hilbertpts)
                        if parameters.get("plotEachHilbert"):
                            plot_geometry(hilbertpts,changecolor=True)
                            plot_geometry(layer.solidPolys)
                            plt.title("Debug")
                            plt.axis('square')
                            plt.show()
                if modify:
                    modifiedlayer=Layer([],parameters,idl) # copy the other infos if needed: future to do
                    isInjected=False
                    hilbertIsInjected=False
                    curPrintSpeed="G1 F600"
                    messedWithSpeed=False
                    messedWithFan=False
                    layer.prepareDeletion(featurename="Bridge",polys=layer.validpolys)
                    if len(layer.oldpolys)>0:
                        layer.prepareDeletion(featurename=":Solid",polys=layer.oldpolys)
                    #print("FEATURES:",[(f[0],f[2]) for f in layer.features])
                    injectionStart=None
                    print("modifying GCode")
                    for idline,line in enumerate(layer.lines):
                        if layer.validpolys:
                            if ";TYPE" in line and not isInjected:#inject arcs at the very start
                                injectionStart=idline
                                modifiedlayer.lines.append(";TYPE:Arc infill\n")
                                modifiedlayer.lines.append(f"M106 S{parameters.get('ArcFanSpeed')}\n")
                                for overhangline in arcOverhangGCode:
                                    for arcline in overhangline:
                                        for cmdline in arcline:
                                            modifiedlayer.lines.append(cmdline)
                                isInjected=True
                                #add restored pre-injected tool position
                                for id in reversed(range(injectionStart)):
                                    if "X" in layer.lines[id]:
                                        modifiedlayer.lines.append(layer.lines[id])
                                        break
                        if layer.oldpolys:
                            if ";TYPE" in line and not hilbertIsInjected:# startpoint of solid infill: print all hilberts from here.
                                hilbertIsInjected=True
                                injectionStart=idline
                                modifiedlayer.lines.append(";TYPE:Solid infill\n")
                                modifiedlayer.lines.append(f"M106 S{parameters.get('aboveArcsFanSpeed')}\n")
                                hilbertGCode=hilbert2GCode(allhilbertpts,parameters,layer.height)
                                modifiedlayer.lines.extend(hilbertGCode)
                                #add restored pre-injected tool position
                                for id in reversed(range(injectionStart)):
                                    if "X" in layer.lines[id]:
                                        modifiedlayer.lines.append(layer.lines[id])
                                        break
                        if "G1 F" in line.split(";")[0]:#special block-speed-command
                            curPrintSpeed=line    
                        if layer.exportThisLine(idline):
                            if layer.isClose2Bridging(line,parameters.get("CoolingSettingDetectionDistance")):
                                if not messedWithFan:
                                    modifiedlayer.lines.append(f"M106 S{parameters.get('aboveArcsFanSpeed')}\n")
                                    messedWithFan=True
                                modline=line.strip("\n")+ f" F{parameters.get('aboveArcsPerimeterPrintSpeed')}\n"     
                                modifiedlayer.lines.append(modline)
                                messedWithSpeed=True
                            else:
                                if messedWithFan and not parameters.get("applyAboveFanSpeedToWholeLayer"):
                                    modifiedlayer.lines.append(f"M106 S{layer.fansetting:.0f}\n")
                                    messedWithFan=False
                                if messedWithSpeed:
                                    modifiedlayer.lines.append(curPrintSpeed+"\n")
                                    messedWithSpeed=False
                                modifiedlayer.lines.append(line)
                    if messedWithFan:
                        modifiedlayer.lines.append(f"M106 S{layer.fansetting:.0f}\n")
                        messedWithFan=False        
                    layerobjs[idl]=modifiedlayer  # overwrite the infos
    if gcodeWasModified:
        overwrite=True
        if parameters.get("Path2Output"):
            path2GCode=parameters.get("Path2Output")
            overwrite=False
        f=open(path2GCode,"w")
        if overwrite:
            print("overwriting file")
        else: 
            print("write to",path2GCode)    
        for layer in layerobjs:
            f.writelines(layer.lines)
        f.close()   
    else:
        print(f"Analysed {len(layerobjs)} Layers, but no matching overhangs found->no arcs generated. If unexpected: look if restricting settings like 'minArea' or 'MinBridgeLength' are correct.")     
    #os.startfile(path2GCode, 'open')
    print("Script execution complete.")
    if not skipInput:
        input("Press enter to exit.")

################################# HELPER FUNCTIONS GCode->Polygon #################################
###################################################################################################

def getFileStreamAndPath(read=True):
    if len(sys.argv) != 2:
        print("Usage: python3 ex1.py <filename>")
        sys.exit(1)
    filepath = sys.argv[1]
    try:
        if read:
            f = open(filepath, "r")
        else:
            f=open(filepath, "w")    
        return f,filepath
    except IOError:
        input("File not found.Press enter.")
        sys.exit(1)
        
def splitGCodeIntoLayers(gcode:list)->list:
    gcode_list = []
    buff=[]
    for linenumber,line in enumerate(gcode):
        if ";LAYER_CHANGE" in line:
            gcode_list.append(buff)
            buff=[]
            buff.append(line)
        else:
            buff.append(line)
    gcode_list.append(buff)  #catch last layer
    print("last read linenumber:",linenumber)            
    return gcode_list
            
def getPtfromCmd(line:str)->Point:
    x=None
    y=None
    line=line.split(";")[0]
    cmds=line.split(" ")
    for c in cmds:
        if "X" in c:
            x=float(c[1:])
        elif "Y" in c:
            y=float(c[1:])
    if (x is not None) and (y is not None):
        p=Point(x,y)
    else:
        p=None    
    return p        

def makePolygonFromGCode(lines:list)->Polygon:
    pts=[]
    for line in lines:
        if ";WIPE" in line:
            break
        if "G1" in line:
            p=getPtfromCmd(line)
            if p:
                pts.append(p)
    if len(pts)>2:
        return Polygon(pts)
    else:
        #print("invalid poly: not enough pts")
        return None  

################################# CLASSES #################################
###########################################################################
   
class Layer():
    def __init__(self,lines:list=[],kwargs:dict={},layernumber:int=-1)->None:
        self.lines=lines
        self.layernumber=layernumber
        self.z=kwargs.get("z",None)
        self.polys=[]
        self.validpolys=[]
        self.extPerimeterPolys=[]
        self.binfills=[]
        self.features=[]
        self.oldpolys=[]
        self.dontPerformPerimeterCheck=kwargs.get('notPerformPerimeterCheck',False)
        self.deleteTheseInfills=[]
        self.deletelines=[]
        self.associatedIDs=[]
        self.sinfills=[]
        self.parameters=kwargs
        self.lastP=None
    def extract_features(self)->None:
        buff=[]
        currenttype=""
        start=0
        for idl,line in enumerate(self.lines):
            if ";TYPE:" in line:
                if currenttype:
                    self.features.append([currenttype,buff,start])
                    buff=[]
                    start=idl                        
                currenttype=line
            else:
                buff.append(line)  
        self.features.append([currenttype,buff,start])# fetch last one
    def addZ(self,z:float=None)->None:
        if z:
            self.z=z
        else:
            for l in self.lines:
                cmd=l.split(";")[0] # work only on the command itself
                if "G1" in cmd and "Z" in cmd:
                    cmds=cmd.split(" ")
                    for c in cmds:        
                        if "Z" in c:
                            self.z=float(c[1:])
                            return
    def addHeight(self):
        for l in self.lines:
            if ";HEIGHT" in l:
                h=l.split(":")
                self.height=float(h[-1])
                return
        warnings.warn(f"Layer {self.layernumber}: no height found, using layerheight default!")
        self.height=self.parameters.get("layer_height")         
    def getRealFeatureStartPoint(self,idf:int)->Point:
        """ since GCode only stores destination of the move, the origin of the first move has to be included.""" 
        if idf<1:
            return None
        lines=self.features[idf-1][1]
        for line in reversed(lines):
            if "G1" in line:
                return getPtfromCmd(line)

    def makeExternalPerimeter2Polys(self)->None:
        extPerimeterIsStarted=False
        for idf,fe in enumerate(self.features):
            ftype=fe[0]
            lines=fe[1]
            
            if "External" in ftype or ("Overhang" in ftype and extPerimeterIsStarted) or ("Overhang" in ftype and self.dontPerformPerimeterCheck): #two different types of perimeter to for a poly: external perimeter and overhang perimeter + option for manual errorhandling, when there is no feature "external"
                if not extPerimeterIsStarted:
                    linesWithStart=[]
                    if idf>1:
                        pt=self.getRealFeatureStartPoint(idf)
                        if type(pt)==type(Point):
                            linesWithStart.append(p2GCode(pt))
                        else:
                            warnings.warn(f"Layer {self.layernumber}: Could not fetch real StartPoint.")
                linesWithStart=linesWithStart+lines
                extPerimeterIsStarted=True
            if (idf==len(self.features)-1 and extPerimeterIsStarted) or (extPerimeterIsStarted and not ("External" in ftype or "Overhang" in ftype)) :#finish the poly if end of featurelist or different feature
                poly=makePolygonFromGCode(linesWithStart)
                if poly:
                    self.extPerimeterPolys.append(poly) 
                extPerimeterIsStarted=False   
    def makeStartLineString(self,poly:Polygon,kwargs:dict={}):
        if not self.extPerimeterPolys:
            self.makeExternalPerimeter2Polys()
        if len(self.extPerimeterPolys)<1:
            warnings.warn(f"Layer {self.layernumber}: No ExternalPerimeterPolys found in prev Layer")
            return None,None   
        for ep in self.extPerimeterPolys:
            ep=ep.buffer(1e-2)# avoid self intersection error
            if ep.intersects(poly):
                startArea=ep.intersection(poly)
                startLineString=startArea.boundary.intersection(poly.boundary.buffer(1e-2))
                if startLineString.is_empty:
                    if poly.contains(startArea):#if inside no boundarys can overlap.
                        startLineString=startArea.boundary
                        boundaryLineString=poly.boundary
                        if startLineString.is_empty:#still empty? unlikely to happen       
                            plt.title("StartLineString is None")
                            plot_geometry(poly,'b')
                            plot_geometry(startArea,filled=True)
                            plot_geometry([ep for ep in self.extPerimeterPolys])  
                            plt.legend(["currentLayerPoly","StartArea","prevLayerPoly"])
                            plt.axis('square')
                            plt.show()  
                            warnings.warn(f"Layer {self.layernumber}: No Intersection in Boundary,Poly+ExternalPoly")
                            return None,None
                else:    
                    boundaryLineString=poly.boundary.difference(startArea.boundary.buffer(1e-2))
                #print("STARTLINESTRING TYPE:",startLineString.geom_type)  
                if kwargs.get("plotStart"):
                    print("Geom-Type:",poly.geom_type)
                    plot_geometry(poly,color="b")
                    plot_geometry(ep,'g')
                    plot_geometry(startLineString,color="m")
                    plt.title("Start-Geometry")
                    plt.legend(["Poly4ArcOverhang","External Perimeter prev Layer","StartLine for Arc Generation"])
                    plt.axis('square')
                    plt.show()  
                return startLineString,boundaryLineString
        #end of for loop, and no intersection found        
        plt.title("no intersection with prev Layer Boundary")
        plot_geometry(poly,'b')
        plot_geometry([ep for ep in self.extPerimeterPolys])  
        plt.legend(["currentLayerPoly","prevLayerPoly"])
        plt.axis('square')
        plt.show()  
        warnings.warn(f"Layer {self.layernumber}: No intersection with prevLayer External Perimeter detected") 
        return None,None

    def mergePolys(self,thesepolys:list=None)-> list:
        if not thesepolys:
            thesepolys=self.polys
        mergedPolys = unary_union(thesepolys)
        #print("Merged Geometry Type:",mergedPolys.geom_type)
        if mergedPolys.geom_type=="Polygon":
            thesepolys=[mergedPolys]
        elif mergedPolys.geom_type=="MultiPolygon" or mergedPolys.geom_type=="GeometryCollection":
            thesepolys=[poly for poly in mergedPolys.geoms] 
        return thesepolys
    def spotFeaturePoints(self,featureName:str,splitAtWipe=False,includeRealStartPt=False, splitAtTravel=False)->list:
        parts=[]
        for idf,fe in enumerate(self.features):
            ftype=fe[0]
            lines=fe[1]
            start=fe[2]
            pts=[]
            isWipeMove=False
            travelstr=f"F{self.parameters.get('travel_speed')*60}"
            if featureName in ftype:
                if includeRealStartPt and idf>0:
                    sp=self.getRealFeatureStartPoint(idf)
                    if sp:pts.append(sp)       
                for line in lines:
                    if "G1" in line and (not isWipeMove):
                        if (not "E" in line) and travelstr in line and splitAtTravel:
                            #print(f"Layer {self.layernumber}: try to split feature. No. of pts before:",len(pts))
                            if len(pts)>=2:#make at least 1 ls
                                parts.append(pts)
                                pts=[]# update self.features... TODO
                        elif "E" in line:     #maybe fix error of included travel moves? 
                            p=getPtfromCmd(line)
                            if p:
                                pts.append(p)
                    if 'WIPE_START' in line:
                        isWipeMove=True
                        if splitAtWipe:
                            parts.append(pts)
                            pts=[]
                    if 'WIPE_END' in line:
                        isWipeMove=False                  
                if len(pts)>1:#fetch last one
                    parts.append(pts)           
        return parts                     
    def spotSolidInfill(self)->None:
        parts=self.spotFeaturePoints("Solid infill",splitAtTravel=True)
        for infillpts in parts:
            if self.verifySolidInfillPts(infillpts):
                self.sinfills.append(LineString(infillpts))
    def makePolysFromSolidInfill(self,extend:float=1)->None:
        self.solidPolys=[]
        for sInfill in self.sinfills:
            infillPoly=sInfill.buffer(extend)
            self.solidPolys.append(infillPoly)
            if self.parameters.get("plotDetectedSolidInfillPoly"):
                plot_geometry(infillPoly)
                plot_geometry(sInfill,"g")
                plt.axis('square')
                plt.show()
    def verifySolidInfillPts(self,infillpts:list)->bool:
        '''Verify SollidInfillPts by checking if >=1 of the Points is inside the desired polygon-locations.'''
        for p in infillpts:
                for poly in self.oldpolys:
                    if poly.contains(p):
                        return True          
        return False   

    def spotBridgeInfill(self)->None:
        parts=self.spotFeaturePoints("Bridge infill",splitAtTravel=True)
        for idf,infillpts in enumerate(parts):
            self.binfills.append(BridgeInfill(infillpts))
    def makePolysFromBridgeInfill(self,extend:float=1)->None:
        for bInfill in self.binfills:
            infillPts=bInfill.pts
            infillLS=LineString(infillPts)
            infillPoly=infillLS.buffer(extend)
            self.polys.append(infillPoly)
            self.associatedIDs.append(bInfill.id)
            if self.parameters.get("plotDetectedInfillPoly"):
                plot_geometry(infillPoly)
                plot_geometry(infillLS,"g")
                plt.axis('square')
                plt.show()
    def getOverhangPerimeterLineStrings(self):
        parts=self.spotFeaturePoints("Overhang perimeter",includeRealStartPt=True)
        if parts:
            return [LineString(pts) for pts in parts]
        else:
            return []    
    def verifyinfillpolys(self,minDistForValidation:float=0.5)->None:
        '''Verify a poly by measuring the distance to any overhang parameters. Valid if measuredDist<minDistForValidation'''
        overhangs=self.getOverhangPerimeterLineStrings()
        if len(overhangs)>0:
            if self.parameters.get("PrintDebugVerification"):print(f"Layer {self.layernumber}: {len(overhangs)} Overhangs found")
            allowedSpacePolygon=self.parameters.get("AllowedSpaceForArcs")
            if not allowedSpacePolygon:
                input(f"Layer {self.layernumber}: no allowed space Polygon provided to layer obj, unable to run script. Press Enter.")
                raise ValueError(f"Layer {self.layernumber}: no allowed space Polygon provided to layer obj")
            if self.parameters.get("PrintDebugVerification"):print("No of Polys:",len(self.polys))    
            for idp,poly in enumerate(self.polys):
                if not poly.is_valid:
                    if self.parameters.get("PrintDebugVerification"):print(f"Layer {self.layernumber}: Poly{idp} is (shapely-)invalid")
                    continue
                if (not allowedSpacePolygon.contains(poly)) and self.parameters.get("CheckForAllowedSpace"):
                    if self.parameters.get("PrintDebugVerification"):print(f"Layer {self.layernumber}: Poly{idp} is not in allowedSpacePolygon")
                    continue
                if poly.area<self.parameters.get("MinArea"):
                    if self.parameters.get("PrintDebugVerification"):print(f"Layer {self.layernumber}: Poly{idp} has to little area: {poly.area:.2f}")
                    continue               
                for ohp in overhangs:
                    if poly.distance(ohp)<minDistForValidation:
                        if ohp.length>self.parameters.get("MinBridgeLength"):
                            self.validpolys.append(poly)
                            self.deleteTheseInfills.append(idp)
                            break
                if self.parameters.get("PrintDebugVerification"):print(f"Layer {self.layernumber}: Poly{idp} is not close enough to overhang perimeters")        

    
    def prepareDeletion(self,featurename:str="Bridge",polys:list=None)->None:
        if not polys:
            polys=self.validpolys
        for idf,fe in enumerate(self.features):
            ftype=fe[0]
            lines=fe[1]
            start=fe[2]
            deleteThis=False
            if featurename in ftype:
                for poly in polys:
                    for line in lines:
                        p=getPtfromCmd(line)
                        if p:
                            if poly.contains(p):
                                deleteThis=True
                                break
                        if deleteThis:
                            break 
                if deleteThis:           
                    if idf<len(self.features)-1:
                        end=self.features[idf+1][2]-1 # TODO: prevent deletion of last travel move.
                    else:
                        end=len(self.lines) 
                    self.deletelines.append([start,end])
    def exportThisLine(self,linenumber:int)->bool:
        export=True
        if len(self.deletelines)>0:
            for d in self.deletelines:
                if linenumber>=d[0] and linenumber<=d[1]:
                    export=False
        return export            

    def createHilbertCurveInPoly(self,poly:Polygon):
        print("making hilbert surface")
        dimensions=2
        w=self.parameters.get("solid_infill_extrusion_width")
        a=self.parameters.get("HilbertFillingPercentage")/100
        mmBetweenTravels=(self.parameters.get("aboveArcsInfillPrintSpeed")/60)*self.parameters.get("HilbertTravelEveryNSeconds")
        minX, minY, maxX, maxY=poly.bounds
        lx=maxX-minX
        ly=maxY-minY
        l=max(lx,ly)
        #Iterationcount Math explained: 
        # startpoint: l/w=number of needed segments. segments=(2**iterationcount)-1. Solved for iterationcount.
        iterationCount=int(np.ceil(np.log((a*l+w)/w)/np.log(2))) # + applied ceiling function to ensucre full coverage.
        scale=w/a#l/(2**iterationCount-1)/a
        maxidx=int(2**(dimensions* iterationCount) - 1)
        locs = decode(np.arange(maxidx), 2, iterationCount)# hilbertidx->(x,y) first argument: idx, second: dimensions, third: bits per dim
        #move the curve 1 point in the smaller direction every second layer=>web the curves in z together by overlapping.
        movX=self.layernumber%2*w/a
        movY=self.layernumber%2*w/a
        x=locs[:,0]*scale+minX-movX
        y=locs[:,1]*scale+minY-movY
        hilbertPointsRaw=[[xi,yi] for xi,yi in zip(x.tolist(),y.tolist())]
        noEl=int(np.ceil(mmBetweenTravels/scale))
        buff=[]
        compositeList=[]
        #divide in subset of n elements and shuffle them to prevent localized overheating.
        for el in hilbertPointsRaw:
            p=Point(el)
            if p.within(poly):
                buff.append(p)
            else:
                if len(buff)>5:#neglegt very small pieces
                    if len(buff)>noEl*1.7:
                        compositeList.extend([buff[x:x+noEl] for x in range(0, len(buff),noEl)])
                    else:    
                        compositeList.append(buff)
                buff=[]#delete single pts if there.
        if len(buff)>5:
            compositeList.append(buff) #catch last one
        random.shuffle(compositeList)
        return compositeList
    def isClose2Bridging(self,line:str,minDetectionDistance:float=3):
        if not "G1" in line:
            return False
        p=getPtfromCmd(line)
        if not p:
            return False
        if not self.lastP:
            self.lastP=Point(p.x-0.01,p.y-0.01)    
        ls=LineString([p,self.lastP])
        self.lastP=p
        for poly in self.oldpolys:
            if ls.distance(poly)<minDetectionDistance:
                return True
        return False        
    def spotFanSetting(self,lastfansetting:float):
        for line in self.lines:
            if "M106" in line.split(";")[0]:
                svalue=line.strip("\n").split(";")[0].split(" ")[1]
                self.fansetting=float(svalue[1:])
                return self.fansetting
        self.fansetting=lastfansetting
        return lastfansetting        



            
class Arc():
    def __init__(self,center:Point,r:float,kwargs:dict={}) -> None:
        self.center=center
        self.r=r
        self.pointsPerCircle=kwargs.get("PointsPerCircle",80)
        self.parameters=kwargs
    def setPoly(self,poly:Polygon)->None:
        self.poly=poly    
    def extractArcBoundary(self):
        circ=create_circle(self.center,self.r,self.pointsPerCircle)    
        trueArc=self.poly.boundary.intersection(circ.boundary.buffer(1e-2))
        if trueArc.geom_type=='MultiLineString':
            merged=linemerge(trueArc)
        elif trueArc.geom_type=='LineString':
            self.arcline=trueArc
            return trueArc
        else:
            #print("Other Geom-Type:",trueArc.geom_type)
            merged=linemerge(MultiLineString([l for l in trueArc.geoms if l.geom_type=='LineString']))
        if merged.geom_type=="LineString":
            self.arcline=merged
            return merged                             
        elif merged.geom_type=="MultiLineString":
            arcList=[]
            for ls in merged.geoms:
                arc=Arc(self.center,self.r,self.parameters)
                arc.arcline=ls
                arcList.append(arc)
            return arcList
        else:
            input("ArcBoundary merging Error.Unable to run script. Press Enter.")
            raise ValueError("ArcBoundary merging Error")
    def generateConcentricArc(self,startpt:Point,remainingSpace:Polygon)->Polygon:
        circ=create_circle(startpt,self.r,self.pointsPerCircle)
        arc=circ.intersection(remainingSpace)
        self.poly=arc
        return arc            

class BridgeInfill():
    def __init__(self,pts=[],id=random.randint(1,int(1e10))) -> None:
        self.pts=pts
        self.deleteLater=False
        self.id=id

################################# HELPER FUNCITONS Polygon->Arc #################################
################################################################################################# 

def midpoint(p1:Point, p2:Point):
    return Point((p1.x + p2.x)/2, (p1.y + p2.y)/2)

def getStartPtOnLS(ls:LineString,kwargs:dict={},choseRandom:bool=False)->Point:
    if ls.geom_type=="MultiLineString" or ls.geom_type=="GeometryCollection":
        lengths=[]
        for lss in ls.geoms:
            if lss.geom_type=="LineString":
                lengths.append(lss.length)
            else:
                print("Startline Item bizzare Type of geometry:",lss.geom_type)    
                lengths.append(0)      
        lsidx=np.argmax(lengths)
        if not lsidx.is_integer():
            try:
                lsidx=lsidx[0]#if multiple max values: take first occurence
            except:
                print("Exception used for lsidx, should be int:", lsidx)
                lsidx=0
        ls=ls.geoms[lsidx]
    if len(ls.coords)<2:
        warnings.warn("Start LineString with <2 Points invalid")
        input("Can not run script, gcode unmodified. Press Enter")
        raise ValueError("Start LineString with <2 Points invalid")
    if len(ls.coords)==2:
        return midpoint(Point(ls.coords[0]),Point(ls.coords[1]))
    scores=[]
    curLength=0
    pts=[Point(p) for p in ls.coords]
    if choseRandom:
        return random.choice(pts)
    coords=[np.array(p) for p in ls.coords]
    for idp,p in enumerate(pts):
        if idp==0 or idp==len(pts)-1:
            scores.append(0)
            continue
        curLength+=p.distance(pts[idp-1])
        relLength=curLength/ls.length
        lengthscore=1-np.abs(relLength-0.5)#Hat-function: pointscore=1 at relLength=0.5, 0 at start or end.
        v1=coords[idp]-coords[idp-1]
        v2=coords[idp+1]-coords[idp]
        if np.linalg.norm(v1)>0 and np.linalg.norm(v2)>0:#calc angle only for non-zero-vectors
            v1=v1/np.linalg.norm(v1)
            v2=v2/np.linalg.norm(v2)
            anglescore=np.abs(np.sin(np.arccos(np.clip(np.dot(v1, v2), -1.0, 1.0))))#prefer points at corners
            anglescore*=kwargs.get("CornerImportanceMultiplier",1)
            scores.append(lengthscore+anglescore)
        else:
            scores.append(lengthscore)    
    maxIndex=scores.index(max(scores))
    return pts[maxIndex]

def create_circle(p:Point, radius:float, n:int)->Polygon:
    x=p.x
    y=p.y
    return Polygon([[radius*np.sin(theta)+x, radius*np.cos(theta)+y] for theta in np.linspace(0, 2*np.pi - 2*np.pi/n, int(n))])       

def get_farthest_point(arc:Polygon, base_poly:Polygon, remaining_empty_space:Polygon):#function ported from Steven McCulloch
    """
    Find the point on a given arc that is farthest away from the base polygon.
    In other words, the point on which the largest circle can be drawn without going outside the base polygon.
    Parameters
    ----------
    arc: Polygon
        The arc in question
    base_poly: Polygon
        The base polygon
    remaining_empty_space: Polygon
        The polygon representing the space left to be filled in the base polygon        
    Returns
    -------
    farthest_point: Point
        The point on the arc that is farthest away from the base polygon
    longest_distance: float
        How far away the polygon is from the farthest point
    point_on_poly: Point
        The point on the base polygon that is closest to the arc
    """
    longest_distance = -1
    farthest_point = Point([0, 0])
    pointFound=False
    # Handle input for polygons and LineString
    # The first arc begins on a LineString rather than a Polygon
    if arc.geom_type == 'Polygon':
        arc_coords = arc.exterior.coords
    elif arc.geom_type == 'LineString':
        arc_coords = np.linspace(list(arc.coords)[0], list(arc.coords)[1])
    else:
        print('get_farthest_distance: Wrong shape type given',type(arc))
        plt.title("Function get_farthest_point went wrong")
        plot_geometry(base_poly,"b")
        plot_geometry(arc,"r")
        plt.axis('square')
        plt.show()
    # For every point in the arc, find out which point is farthest away from the base polygon
    for p in list(arc_coords):
        distance = Point(p).distance(base_poly.boundary)
        if (distance > longest_distance) and ((remaining_empty_space.buffer(1e-2).contains(Point(p)))):
            longest_distance = distance
            farthest_point = Point(p)
            pointFound = True
    point_on_poly = nearest_points(base_poly, farthest_point)[0]
    if pointFound:
        return farthest_point, longest_distance, point_on_poly 
    else:
        return None, None, None       

def move_toward_point(start_point:Point, target_point:Point, distance:float)->Point:
    """Moves a point a set distance toward another point"""

    # Calculate the direction in which to move
    dx = target_point.x - start_point.x
    dy = target_point.y - start_point.y

    # Normalize the direction
    magnitude = (dx**2 + dy**2)**0.5
    dx /= magnitude
    dy /= magnitude

    # Move the point in the direction of the target by the set distance
    return Point(start_point.x + dx*distance, start_point.y + dy*distance)        

def redistribute_vertices(geom:LineString, distance:float)->LineString:
    if geom.geom_type == 'LineString':
        num_vert = int(round(geom.length / distance))
        if num_vert == 0:
            num_vert = 1
        return LineString(
            [geom.interpolate(float(n) / num_vert, normalized=True)
             for n in range(num_vert + 1)])
    elif geom.geom_type == 'MultiLineString':
        parts = [redistribute_vertices(part, distance) for part in geom.geoms]
        return type(geom)([p for p in parts if not p.is_empty])
    else:
        warnings.warn('unhandled geometry %s', (geom.geom_type,))
        return geom
    
def generateMultipleConcentricArcs(startpt:Point,rMin:float,rMax:float, boundaryLineString:LineString,remainingSpace:Polygon,kwargs={})->list:
    arcs=[]
    r=rMin
    while r<=rMax:
        arcObj=Arc(startpt,r,kwargs=kwargs)
        arc=arcObj.generateConcentricArc(startpt,remainingSpace)
        if arc.intersects(boundaryLineString) and not kwargs.get("UseLeastAmountOfCenterPoints",False):
            break
        arcs.append(arcObj)
        #print("True Arc type:",type(arc4gcode))
        r+=kwargs.get("ArcWidth")
    return arcs

################################# HELPER FUNCTIONS Arc Validation #################################
################################################################################################### 

def getValueBasedColor(val:float, max_val=10)->tuple:
    normalizedVal = val / max_val
    rgb=[0,0,0]
    rgb[0]=min(normalizedVal,1)
    rgb[2]=1-rgb[0]
    return tuple(rgb)

def plot_geometry(geometry, color='black', linewidth=1,**kwargs):
    if type(geometry)==type([]):
        for idx,geo in enumerate(geometry):
            if kwargs.get("changecolor"):
                color=getValueBasedColor(idx,len(geometry))
            plot_geometry(geo,color=color,linewidth=linewidth,kwargs=kwargs)
    elif geometry.geom_type == 'Point':
        x, y = geometry.x, geometry.y
        plt.scatter(x, y, color=color, linewidth=linewidth)        
    elif geometry.geom_type == 'LineString':
        x, y = geometry.xy
        plt.plot(x, y, color=color, linewidth=linewidth)
    elif geometry.geom_type == 'Polygon':
        x, y = geometry.exterior.xy
        plt.plot(x, y, color=color, linewidth=linewidth)
        if kwargs.get("filled"):
            plt.fill(x,y,color=color,alpha=0.8)
        for interior in geometry.interiors:
            x, y = interior.xy
            plt.plot(x, y, color=color, linewidth=linewidth)
            if kwargs.get("filled_holes"):
                plt.fill(x,y,color=color,alpha=0.5)
    elif geometry.geom_type == 'MultiLineString':
        for line in geometry.geoms:
            x, y = line.xy
            plt.plot(x, y, color=color, linewidth=linewidth)
    elif geometry.geom_type == 'MultiPolygon' or geometry.geom_type == "GeometryCollection":
        for polygon in geometry.geoms:
            plot_geometry(polygon,color=color,linewidth=linewidth,kwargs=kwargs)
    else:
        print('Unhandled geometry type: ' + geometry.geom_type)

################################# HELPER FUNCTIONS Arc->GCode #################################
############################################################################################### 

def getArcBoundarys(concentricArcs:list)->list:
    '''Handle arcs composited from multiple parts'''
    boundarys=[]
    for arc in concentricArcs:
        arcLine=arc.extractArcBoundary()
        if type(arcLine)==type([]):
            for arc in arcLine:
                boundarys.append(arc.arcline)
        else:
            boundarys.append(arcLine)
    return boundarys                

def readSettingsFromGCode2dict(gcodeLines:list,fallbackValuesDict:dict)->dict:
    gCodeSettingDict=fallbackValuesDict
    isSetting=False
    for line in gcodeLines:
        if "; prusaslicer_config = begin" in line:
            isSetting=True
            continue
        if isSetting :
            setting=line.strip(";").strip("\n").split("= ")
            if len(setting)==2:
                try:
                    gCodeSettingDict[setting[0].strip(" ")]=literal_eval(setting[1]) # automaticly convert into int,float,...
                except:
                    gCodeSettingDict[setting[0].strip(" ")]=setting[1] # leave the complex settings as strings. They shall be handled individually if necessary 
            elif len(setting)>2:
                gCodeSettingDict[setting[0].strip(" ")]=setting[1:]
                warnings.warn(f"PrusaSlicer Setting {setting[0]} not in the expected key/value format, but added into the settings-dictionarry")
            else:    
                print("Could not read setting from PrusaSlicer:",setting)
    if "%" in str(gCodeSettingDict.get("perimeter_extrusion_width")) : #overwrite Percentage width as suggested by 5axes via github                
        gCodeSettingDict["perimeter_extrusion_width"]=gCodeSettingDict.get("nozzle_diameter")*(float(gCodeSettingDict.get("perimeter_extrusion_width").strip("%"))/100)
    isWarned=False    
    for key,val in gCodeSettingDict.items():
        if isinstance(val,tuple) :
            if gCodeSettingDict.get("Fallback_"+key):
                gCodeSettingDict[key]=gCodeSettingDict.get("Fallback_"+key)
                #warnings.warn(f"{key}: Fallback value used: {gCodeSettingDict.get(key)}")
            else:
                gCodeSettingDict[key]=val[0]    
                if not isWarned:
                    warnings.warn(f"{key} was specified as tuple/list, this is normal for using multiple extruders. For all list values First values will be used. If unhappy: Add manual fallback value by searching for ADD FALLBACK in the code. And add 'Fallback_<key>:<yourValue>' into the dictionary.")
                    isWarned=True
    return gCodeSettingDict

def checkforNecesarrySettings(gCodeSettingDict:dict)->bool:
    if not gCodeSettingDict.get("use_relative_e_distances"):
        warnings.warn("Script only works with relative e-distances enabled in PrusaSlicer. Change acordingly.")
        return False
    if gCodeSettingDict.get("extrusion_width")<0.001 or gCodeSettingDict.get("perimeter_extrusion_width")<0.001 or gCodeSettingDict.get("solid_infill_extrusion_width")<0.001:
        warnings.warn("Script only works with extrusion_width and perimeter_extrusion_width and solid_infill_extrusion_width>0. Change in PrusaSlicer acordingly.")
        return False    
    if not gCodeSettingDict.get("overhangs"):
        warnings.warn("Overhang detection disabled in PrusaSlicer. Activate in PrusaSlicer for script success!")
        return False
    if gCodeSettingDict.get("bridge_speed")>5:
        warnings.warn(f"Your Bridging Speed is set to {gCodeSettingDict.get('bridge_speed'):.0f} mm/s in PrusaSlicer. This can cause problems with warping.<=5mm/s is recommended")        
    if gCodeSettingDict.get("infill_first"):
        warnings.warn("Infill set in PrusaSlicer to be printed before perimeter. This can cause problems with the script.")
    if gCodeSettingDict.get("external_perimeters_first"):
        warnings.warn("PrusaSlicer-Setting: External perimeter is printed before inner perimeters. Change for better overhang performance. ")
    if not gCodeSettingDict.get("avoid_crossing_perimeters"):
        warnings.warn("PrusaSlicer-Setting: Travel Moves may cross the outline and therefore cause artefacts in arc generation.")    
    return True
def calcEStepsPerMM(settingsdict:dict,layerheight:float=None)->float:
    if layerheight:# case: printing on surface.
        w=settingsdict.get("infill_extrusion_width")
        h=layerheight
        eVol=(w-h)*h+np.pi*(h/2)**2 *settingsdict.get("HilbertInfillExtrusionMultiplier",1)
    else:   #case: bridging, used for arcs. 
        eVol = (settingsdict.get("nozzle_diameter")/2)**2 * np.pi *settingsdict.get("ArcExtrusionMultiplier",1)#printing in midair will result in circular shape. Scource: https://manual.slic3r.org/advanced/flow-math
    if settingsdict.get("use_volumetric_e"):
        return eVol
    else:
        eInMm=eVol/((settingsdict.get("filament_diameter")/2)**2 *np.pi)
        return eInMm

def p2GCode(p:Point,E=0,**kwargs)->str:
    line=f"G1 X{p.x:.6} Y{p.y:.6} "
    line+="E0" if E==0 else f"E{E:.7f}"
    if kwargs.get('F'):
        line+=f" F{kwargs.get('F'):0d}"
    line+='\n'       
    return line  

def retractGCode(retract:bool=True,kwargs:dict={})->str:
    retractDist=kwargs.get("retract_length",1)
    E= -retractDist if retract else retractDist
    return f"G1 E{E} F{kwargs.get('retract_speed',35)*60}\n"  

def setFeedRateGCode(F:int)->str:
    return f"G1 F{F}\n"     

def arc2GCode(arcline:LineString,eStepsPerMM:float,arcidx=None,kwargs={})->list:
    GCodeLines=[]
    p1=None
    pts=[Point(p) for p in arcline.coords]
    if len(pts)<2:
        return []
    #plt.plot([p.x for p in pts],[p.y for p in pts])
    #plt.axis('square')
    #plt.show()      
    extDist=kwargs.get("ExtendArcDist",0.5)
    pExtend=move_toward_point(pts[-2],pts[-1],extDist)
    arcPrintSpeed=np.clip(arcline.length/(kwargs.get("ArcSlowDownBelowThisDuration",3))*60,
                            kwargs.get("ArcMinPrintSpeed",1*60),kwargs.get('ArcPrintSpeed',2*60)) # *60 bc unit conversion:mm/s=>mm/min
    for idp,p in enumerate(pts):
        if idp==0:
            p1=p
            GCodeLines.append(f";Arc {arcidx if arcidx else ' '} Length:{arcline.length}\n")
            GCodeLines.append(p2GCode(p,F=kwargs.get('ArcTravelFeedRate',100*60)))#feedrate is mm/min...
            GCodeLines.append(retractGCode(retract=False,kwargs=kwargs))
            GCodeLines.append(setFeedRateGCode(arcPrintSpeed))
        else:
            dist=p.distance(p1)
            if dist>kwargs.get("GCodeArcPtMinDist",0.1):
                GCodeLines.append(p2GCode(p,E=dist*eStepsPerMM))
                p1=p
        if idp==len(pts)-1:
            GCodeLines.append(p2GCode(pExtend,E=extDist*eStepsPerMM))#extend arc tangentially for better bonding between arcs
            GCodeLines.append(retractGCode(retract=True,kwargs=kwargs))
    return GCodeLines        

def hilbert2GCode(allhilbertpts:list,parameters:dict,layerheight:float):
    hilbertGCode=[]
    eStepsPerMM=calcEStepsPerMM(parameters,layerheight)
    for idc,curvepts in enumerate(allhilbertpts):
        for idp,p in enumerate(curvepts):
            if idp==0:
                hilbertGCode.append(p2GCode(p,F=parameters.get("ArcTravelFeedRate")))
                if idc==0:
                    hilbertGCode.append(retractGCode(False,parameters))
            elif idp==1:
                hilbertGCode.append(p2GCode(p,E=eStepsPerMM*p.distance(lastP), F=parameters.get("aboveArcsInfillPrintSpeed")))
            else:    
                hilbertGCode.append(p2GCode(p,E=eStepsPerMM*p.distance(lastP)))
            lastP=p 
        #finish line       
    hilbertGCode.append(retractGCode(True,parameters))    
    return hilbertGCode 

def _warning(message,category = UserWarning, filename = '', lineno = -1,*args, **kwargs):
    print(f"{filename}:{lineno}: {message}")
warnings.showwarning = _warning

################################# MAIN EXECUTION #################################
##################################################################################

def parse_args():
    parser = argparse.ArgumentParser(description="Process G-code files.")
    parser.add_argument('path', type=str, help='Path to the G-code file')
    parser.add_argument('--skip-input', action='store_true', help='Skip any user input prompts (non-Windows only)')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()

    # Get file stream and path based on the provided path
    gCodeFileStream, path2GCode = getFileStreamAndPath(args.path)

    # Determine whether to skip input based on the platform and command line argument
    skipInput = args.skip_input or platform.system() != "Windows"

    # Call the main function with the arguments
    main(gCodeFileStream, path2GCode, skipInput)
