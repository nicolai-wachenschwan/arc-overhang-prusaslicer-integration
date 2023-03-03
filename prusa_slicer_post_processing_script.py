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
Python 3.5+ and the librarys: shapely 1.8+, numpy 1.2+, matplotlib for debugging

Limitations:
-As with your 3d-printer you may need to customize some settings to your specific geometry. The script will inform you how, when Errors occur :)
-Currently deletes all BridgeInfills in layers with arcs...
-while the arcs print fairly straight, the layers above will induce warping.
-The Arcs are extruded very thick, so the layer will be 0.1-0.5mm thicker (dependend on nozzle dia) than expected=>if precision needed make test prints to counter this effect.

Notes:
This code is a little messy. Usually I would devide it into multiple files, but that would compromise the ease of use.
Therefore I divided the code into sections, marked with ###
Feel free to give it some refactoring and add more functionalities!

Future possible extensions:
-slow down all commands 5mm above arcs, to prevent warping, slow down the bridging-speed of the perimeter, if necessary


Known issues:
-pointsPerCircle>80 give weird results
-MaxDistanceFromPerimeter >=2*perimeterwidth=weird result.
-avoid using the code multiple times onto the same gcode, as errors might accumulate.
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

########## Parameters  - adjust values here as needed ##########
def makeFullSettingDict(gCodeSettingDict:dict) -> dict: 
    """Merge Two Dictionarys and set some keys/values explicitly"""
    #the slicer-settings will be imported from GCode. But some are Arc-specific and need to be adapted by you.
    _perimeter_extrusion_width=0.4
    if "%" in str(gCodeSettingDict.get("perimeter_extrusion_width")) :
        _perimeter_extrusion_width=gCodeSettingDict.get("nozzle_diameter")*(float(gCodeSettingDict.get("perimeter_extrusion_width").strip("%"))/100)
    else :
        _perimeter_extrusion_width=float(gCodeSettingDict.get("perimeter_extrusion_width"))

    AddManualSettingsDict={
        #adapt these settings as needed for your specific geometry/printer:
        "AllowedSpaceForArcs": Polygon([[0,0],[500,0],[500,500],[0,500]]),#have control in which areas Arcs shall be generated
        "ArcCenterOffset":2, # Unit:mm, prevents very small Arcs by hiding the center in not printed section. Make 0 to get into tricky spots with smaller arcs.
        "ArcMinPrintSpeed":0.5*60,#Unit:mm/min
        "ArcPrintSpeed":1.5*60, #Unit:mm/min
        "ArcTravelFeedRate":30*60, # slower travel speed, Unit:mm/min
        "ExtendIntoPerimeter":2.0*_perimeter_extrusion_width, #min=0.5extrusionwidth!, extends the Area for arc generation, put higher to go through small passages. Unit:mm
        "MaxDistanceFromPerimeter":2*_perimeter_extrusion_width,#Control how much bumpiness you allow between arcs and perimeter. lower will follow perimeter better, but create a lot of very small arcs. Should be more that 1 Arcwidth! Unit:mm
        "MinArea":5*10,#Unit:mm2
        "MinBridgeLength":5,#Unit:mm
        "RMax":100, # the max radius of the arcs.

        #advanced Settings, you should not need to touch these.
        "ArcExtrusionMultiplier":1.35,
        "ArcSlowDownBelowThisDuration":3,# Arc Time below this Duration =>slow down, Unit: sec
        "ArcWidth":gCodeSettingDict.get("nozzle_diameter")*0.95, #change the spacing between the arcs,should be nozzle_diameter
        "CornerImportanceMultiplier":0.2, # Startpoint for Arc generation is chosen close to the middle of the StartLineString and at a corner. Higher=>Cornerselection more important.
        "DistanceBetweenPointsOnStartLine":0.1,#used for redestribution, if start fails.
        "GCodeArcPtMinDist":0.1, # min Distance between points on the Arcs to for seperate GCode Command. Unit:mm
        "ExtendArcDist":1.0, # extend Arcs tangentially for better bonding bewteen them, only end-piece affected(yet), Unit:mm
        "MinStartArcs":2, # how many arcs shall be generated in first step
        "PointsPerCircle":80, # each Arc starts as a discretized circle. Higher will slow down the code but give more accurate results for the arc-endings. 
        "SafetyBreak_MaxArcNumber":2000, #max Number of Arc Start Points. prevents While loop form running for ever.
        "WarnBelowThisFillingPercentage":90, # fill the overhang at least XX%, else send a warning. Easier detection of errors in small/delicate areas. Unit:Percent
        "UseLeastAmountOfCenterPoints":False, # always generates arcs until rMax is reached, divide the arcs into pieces in needed. reduces the amount of centerpoints.
    
        #settings for easier debugging:
        "plotStart":False, # plot the detected geometry in the prev Layer and the StartLine for Arc-Generation, use for debugging
        "plotArcsEachStep":False, #plot arcs for every filled polygon. use for debugging
        "plotArcsFinal":False, #plot arcs for every filled polygon, when completely filled. use for debugging
        "plotDetectedInfillPoly":False # plot each detected overhang polygon, use for debugging.
        }
    gCodeSettingDict.update(AddManualSettingsDict)
    return gCodeSettingDict

################################# MAIN FUNCTION #################################
#################################################################################    
#at the top, for better reading
def main(gCodeFileStream,path2GCode)->None:
    '''Here all the work is done, therefore it is much to long.'''
    gCodeLines=gCodeFileStream.readlines()
    gCodeSettingDict=readSettingsFromGCode2dict(gCodeLines)
    parameters=makeFullSettingDict(gCodeSettingDict)
    if not checkforNecesarrySettings(gCodeSettingDict):
        warnings.warn("Incompatible Settings used!")
        input("Can not run script, gcode unmodified. Press enter to close.")
        raise ValueError("Incompatible Settings used!") 
    layerobjs=[]
    if gCodeFileStream:
        layers=splitGCodeIntoLayers(gCodeLines)
        gCodeFileStream.close()
        print("layers:",len(layers))
        for idl,layerlines in enumerate(layers):
            layer=Layer(layerlines,parameters,idl)
            layerobjs.append(layer)   
        for idl,layer in enumerate(layerobjs):    
            if idl<1:
                continue # no overhangs in the first layer and dont mess with the setup
            else:
                layer.extract_features()
                layer.spotBridgeInfill()
                layer.makePolysFromBridgeInfill(extend=parameters.get("ExtendIntoPerimeter",1))
                layer.mergePolys()
                layer.verifyinfillpolys()    
                if layer.validpolys:
                    print(f"overhang found layer {idl}:",len(layer.polys))
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
                            warnings.warn("Skipping Polygon because to StartLine Found")
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
                        arcOverhangGCode.append(f"M106 S{np.round(parameters.get('bridge_fan_speed',100)*2.55)}")#turn cooling Fan on at Bridge Setting
                        #for arc in arcs4gcode:
                        #    plot_geometry(arc)
                        #    plot_geometry(Point(arc.coords[0]))
                        #plt.axis('square')
                        #plt.show()
                        for ida,arc in enumerate(arcs4gcode):
                            if not arc.is_empty:    
                                arcGCode=arc2GCode(arcline=arc,eStepsPerMM=eStepsPerMM,arcidx=ida)
                                arcOverhangGCode.append(arcGCode)
                    #all polys finished       
                    modifiedlayer=Layer([],parameters,idl) # copy the other infos if needed: future to do
                    isInjected=False
                    layer.prepareDeletion()
                    #print("FEATURES:",[(f[0],f[2]) for f in layer.features])
                    injectionStart=None
                    for idline,line in enumerate(layer.lines):
                        if ";TYPE" in line and not isInjected:
                            injectionStart=idline
                            modifiedlayer.lines.append(";TYPE:Arc infill\n")
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
                        if layer.exportThisLine(idline):        
                            modifiedlayer.lines.append(line)
                    layerobjs[idl]=modifiedlayer  # overwrite the infos
    f=open(path2GCode,"w")
    print("write to file")
    for layer in layerobjs:
        f.writelines(layer.lines)
    f.close()    
    #os.startfile(path2GCode, 'open')
    print("Code executed successful")
    input("Push enter to close this window")

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
        print("File not found")
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
            
def getPtfromCmd(line:str)->Point | None:
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
        self.parameters=kwargs
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
    def makeStartLineString(self,poly:Polygon,kwargs:dict={})->tuple[LineString,LineString] | tuple[None,None]:
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

    def mergePolys(self):
        mergedPolys = unary_union(self.polys)
        #print("Merged Geometry Type:",mergedPolys.geom_type)
        if mergedPolys.geom_type=="Polygon":
            self.polys=[mergedPolys]
        elif mergedPolys.geom_type=="MultiPolygon" or mergedPolys.geom_type=="GeometryCollection":
            self.polys=[poly for poly in mergedPolys.geoms] 
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
    def verifyinfillpolys(self,minDistForValidation=0.5)->None:
        '''Verify a poly by measuring the distance to any overhang parameters. Valid if measuredDist<minDistForValidation'''
        overhangs=self.getOverhangPerimeterLineStrings()
        if len(overhangs)>0:
            allowedSpacePolygon=self.parameters.get("AllowedSpaceForArcs")
            if not allowedSpacePolygon:
                input(f"Layer {self.layernumber}: no allowed space Polygon provided to layer obj, unable to run script. Press Enter.")
                raise ValueError(f"Layer {self.layernumber}: no allowed space Polygon provided to layer obj")
            for idp,poly in enumerate(self.polys):
                if not poly.is_valid:
                    continue
                if not allowedSpacePolygon.contains(poly):
                    continue
                if poly.area<self.parameters.get("MinArea"):
                    continue               
                for ohp in overhangs:
                    if poly.distance(ohp)<minDistForValidation:
                        if ohp.length>self.parameters.get("MinBridgeLength"):
                            self.validpolys.append(poly)
                            self.deleteTheseInfills.append(idp)
                            break

    
    def prepareDeletion(self)->None:
        for idf,fe in enumerate(self.features):
            ftype=fe[0]
            lines=fe[1]
            start=fe[2]
            deleteThis=False
            if "Bridge" in ftype:
                for poly in self.validpolys:
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
                        end=self.features[idf+1][2]
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

                            
class Arc():
    def __init__(self,center:Point,r:float,kwargs:dict={}) -> None:
        self.center=center
        self.r=r
        self.pointsPerCircle=kwargs.get("PointsPerCircle",80)
        self.parameters=kwargs
    def setPoly(self,poly:Polygon)->None:
        self.poly=poly    
    def extractArcBoundary(self)->LineString|list:
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
    def generateConcentricArc(self,startpt:Point,remainingSpace:Polygon|MultiPolygon)->Polygon:
        circ=create_circle(startpt,self.r,self.pointsPerCircle)
        arc=circ.intersection(remainingSpace)
        self.poly=arc
        return arc            

class BridgeInfill():
    def __init__(self,pts=[],id=random.randint(1,1e10)) -> None:
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

def redistribute_vertices(geom:LineString|MultiLineString, distance:float)->LineString|MultiLineString:
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
    
def generateMultipleConcentricArcs(startpt:Point,rMin:float,rMax:float, boundaryLineString:LineString,remainingSpace:Polygon|MultiPolygon,kwargs={})->list:
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

def readSettingsFromGCode2dict(gcodeLines:list)->dict:
    gCodeSettingDict={}
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
            else:
                print("unmatching setting:",setting)          
    return gCodeSettingDict
def checkforNecesarrySettings(gCodeSettingDict:dict)->bool:
    if not ";AFTER_LAYER_CHANGE" in gCodeSettingDict.get("layer_gcode"):
        warnings.warn("After Layer Change missing keyword, expected: ';AFTER_LAYER_CHANGE' ")
        return False
    if not gCodeSettingDict.get("use_relative_e_distances"):
        warnings.warn("Script only works with relative e-distances. Change acordingly.")
        return False
    if not gCodeSettingDict.get("overhangs"):
        warnings.warn("Overhang detection disabled. Activate for script success!")
        return False    
    if gCodeSettingDict.get("infill_first"):
        warnings.warn("Infill is printed before perimeter. This can cause problems with the script.")
    if gCodeSettingDict.get("external_perimeters_first"):
        warnings.warn("External perimeter is printed before inner perimeters. Change for better overhang performance. ")
    if not gCodeSettingDict.get("avoid_crossing_perimeters"):
        warnings.warn("Travel Moves may cross the outline and therefore cause artefacts in arc generation.")    
    return True
    
def calcEStepsPerMM(settingsdict:dict)->float:
    eVol = (settingsdict.get("nozzle_diameter")/2)**2 * np.pi *settingsdict.get("ArcExtrusionMultiplier",1)#printing in midair will result in circular shape. Scource: https://manual.slic3r.org/advanced/flow-math
    if settingsdict.get("use_volumetric_e"):
        return eVol
    else:
        eInMm=eVol/((settingsdict.get("filament_diameter")/2)**2 *np.pi)
        return eInMm

def p2GCode(p:Point,E=0,**kwargs)->str:
    line=f"G1 X{p.x:.4} Y{p.y:.4} "
    line+="E0" if E==0 else f"E{E:.5f}"
    if kwargs.get('F'):
        line+=f" F{kwargs.get('F'):0d}"
    line+='\n'       
    return line  

def retractGCode(retract=True,kwargs={})->str:
    retractDist=kwargs.get("retract_length",1)
    E= -retractDist if retract else retractDist
    return f"G1 E{E} F{kwargs.get('retract_speed',2100)}\n"  

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
            GCodeLines.append(retractGCode(retract=False))
            GCodeLines.append(setFeedRateGCode(arcPrintSpeed))
        else:
            dist=p.distance(p1)
            if dist>kwargs.get("GCodeArcPtMinDist",0.1):
                GCodeLines.append(p2GCode(p,E=dist*eStepsPerMM))
                p1=p
        if idp==len(pts)-1:
            GCodeLines.append(p2GCode(pExtend,E=extDist*eStepsPerMM))#extend arc tangentially for better bonding between arcs
            GCodeLines.append(retractGCode(retract=True))
    return GCodeLines        

def _warning(message,category = UserWarning, filename = '', lineno = -1,*args, **kwargs):
    print(f"{filename}:{lineno}: {message}")
warnings.showwarning = _warning

################################# MAIN EXECUTION #################################
##################################################################################

if __name__=="__main__":
    gCodeFileStream,path2GCode = getFileStreamAndPath()
    print("path2GCode {}".format(path2GCode))
    main(gCodeFileStream,path2GCode)
