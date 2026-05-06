// i8014W_MagicScan_ISR_Cplusplus.cpp : Defines the entry point for the console application.
//

#include "stdafx.h"
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "..\Lib\pac_i8014W.h"
#pragma comment(lib,"..\\Lib\\pac_i8014W.lib")
int slotIndex=-1;
short jumper;
long TargetCnt=10000;
unsigned long T1,T2;
short chArr[16], gainArr[16], scanChCount;
float sampleRate,realsampleRate;
int scanMode, triggerSource, triggerState;
// prepare data buffers
short hexData[81920];
//  total scaned count
long totalScaned=0;
char GainStr[5][32]={"+/-10V","+/-5V","+/-2.5V","+/-1.25V","+/-20mA"};
char ModeStr[2][32]={"Standard Mode", "Sample and Hold Mode"};
char SourceStr[3][32]={"Software Command", "Internal Interrupt Signal","External Trigger Signal"};
char StateStr[2][32]={"High","Low"};
unsigned short triggerCnt[8]={8,16,32,64,128,256,512,2048};
short triggerLevel=7;
int runFlag=1;
int showCnt=0;
void ShowAI(int slot);
void  Slot_ISR(int slot);
static int IntCnt=0;
int selGain;
int stopFlag=0;
int _tmain(int argc, _TCHAR* argv[])
{
	// TODO: Place code here.
	int slot,ch,c;
	short i,ret;
	int maxCh=8;
	char sTemp[20];
	long readCnt=0;
	printf("\n\n This Demo will show how to use magic scan function to read analog input\n\n");
	printf(" Search I-8014W ....\n");
	for(slot=0;slot<8;slot++){
		if(pac_i8014W_Init(slot)==0){ //find I-8014W module out
			slotIndex=slot;
			break;
		}
	}
	if(slotIndex==-1){
		printf("\t There is no i8014 at Backplane\n");
		Sleep(100);
		exit(0);
	}
	else{
		printf("\t There is an i8014 at slot %d\n",slotIndex);
	}
	jumper= pac_i8014W_GetSingleEndJumper(slotIndex);
	if(jumper)
	{
		maxCh=16;
		printf("\t i8014W Input Mode=Single-End and can have maximum 16 analog input\n\r");
	}
	else
	{
		maxCh=8;
		printf("\t i8014W Input Mode=Differential and can have maximum 8 analog input\n\r");
	}
	// define the sampling channels array chArr[]
	// Differential Mode: element for chArr[] range from channel 0 ~ 7 ,
	// Single ended Mode: element for chArr[] range from channel 0 ~ 15
	// max element counts for chArr[] can be 16
	// define gain type array for each channel
	// gainArr[] element for gainArr[] range from channel 0 ~ 15
	// Gain value : 0="+/-10V",1="+/-5V",2="+/-2.5V",3="+/-1.25V",4="+/-20mA"
	// max element counts for gainArr[] can be 16
start:
	printf ("\n\n Input all i8014W_ConfigMagicScan parameters :\n\r");
	// assigned channel count
	printf("\n Step 1: Define scaned channel counts for magic scan:");
	printf("\n Input scaned channel counts (1~%d) :", maxCh);
	scanf("%s",sTemp);
	scanChCount=atoi(sTemp);
	printf(" Now we have scaned channel counts = %d\n\n",scanChCount);
	// assing input range (gain)
	printf("\n Step 2: Define input range (gain)");
	printf("\n The Gain definition of I-8014W");
	for(i=0;i<5;i++)
	{
		printf ("\n\t Select %d :  %s",i,GainStr[i]);
	}
	printf("\n\r");
	printf (" Select which Gain of (0~4):",i);
	scanf("%s",sTemp);
	selGain = atoi(sTemp);
	for(i=0;i<scanChCount;i++)
	{
		chArr[i]=i;
		gainArr[i]=selGain;
	}
	// assign Sample rate
	printf("\n\n Step 3: Define Sample Rate of I-8014W\n");
	// Sample rate : 1 ~ 250KHz
	printf (" Input Sample rate of 8014W (1~2500000) :");
	scanf("%s",sTemp);
	sampleRate=(float)atol(sTemp);
	printf(" Note: the real sample rate may not the same as user input");
	printf("\n the function i8014W_ConfigMagicScan return code is the \n real sample rate accepted by I-8014W\n");
	// assign scan mode
	// Scan Mode = 1 M1 standard mode, Each Sample clock only samples a single channel
	// Scan Mode = 2 M2 Sample and hold Mode
	printf ("\n\n Step 4:Select Scan Mode of I-8014W:\n");
	printf ("\t Scan Mode 1= M1 Standart Mode \n\t Scan Mode 2= M2 Sample and Hold Mode \n\r");
	printf (" Input Scan Mode of 8014W (1 or 2) :");
	scanf("%s",sTemp);
	scanMode=atoi(sTemp);
	// assign trigger source
	// trigger source 0, start magic scan via polling Mode, software command can only trigger one slot I-8014
	// trigger source 1, start magic scan via internal interrupt signal Mode, internal interrupt signal can trigger all I-8014Ws on slots at the same time.
	// trigger source 2, start magic scan via external trigger signal Mode, extern trigger can also trigger all I-8014Ws on slots at the same time.
	printf ("\n\n Step 5: Select Trigger Source of I-8014W,\n I-8014W can have 3 types of trigger source \n");
	printf ("\t trigger source 0= Software Command \n\t trigger source 1= Internal Interrupt Signal \n\t trigger source 2= External Tigger Signal\n\r");
	printf (" Input trigger source of 8014W (0~2) :");
	scanf("%s",sTemp);
	triggerSource=atoi(sTemp);
	// assign external trigger state
	// triggerState only related with external DI trigger signal.
	// if triggerState 0, external DI trigger signal must be high to start magic scan (default)
	// if triggerState 1, external DI trigger signal must be low to start magic scan
	printf ("\n\n Step6: Select Trigger State of I-8014W if select external trigger source.\n");
	if(triggerSource==2)
	{
		printf ("\t trigger State 0= external trigger singal high to start magic scan \n\t trigger State 1= external trigger signal low to start magic scan\n\r");
		printf (" Input trigger State of I-8014W (0 or 1) :");
		scanf("%s",sTemp);
		triggerState=atoi(sTemp);
	}
	else
	{
		printf ("\t Not external trigger source, trigger state =0 \n");
		triggerState=0;
	}
	// When Configure Sample Rate of Magic Scan, the result sample rate may be different from input sample rate
	// Note i8014W_ConfigMagicScan only tell I-8014W how to start magic scan,it will not start magic scan
	// We have to call i8014W_StartMagicScan to start up the magic scan.
	pac_i8014W_ConfigMagicScan(slotIndex,chArr,gainArr,scanChCount, sampleRate, scanMode,triggerSource,triggerState, &realsampleRate);
	//// test for another I-8014W at next slot
	//pac_i8014W_ConfigMagicScan(slotIndex+1,chArr,gainArr,scanChCount, sampleRate, scanMode,triggerSource,triggerState, &realsampleRate);
	printf("\n\nThe Magic Scan Configurations of I-8014W are:\n");
	printf("\t Scan channel count = %d\n", scanChCount);
	for(i=0;i<scanChCount;i++)
	{
		printf("\t CH[%d]= %d\t Gain[%d]= %d ( %s )\n",i, chArr[i],i, gainArr[i], GainStr[gainArr[i]]);
	}
	printf("\t Scan Mode = %d ( %s )\n", scanMode, ModeStr[scanMode-1]);
	printf("\t Trigger Source = %d ( %s )\n", triggerSource, SourceStr[triggerSource]);
	if(triggerSource==2)
		printf("\t Trigger State = %d ( %s )\n", triggerState, StateStr[triggerState]);
	else
		printf("\t Trigger State = %d ( No need for External Trigger Signal )\n", triggerState);
	printf("\t Set Sample Rate = %6.3f  Real Sample Rate = %6.3f \n",sampleRate, realsampleRate);
	printf("The Interrupt ISR will be triggered when FIFO reach %d count \n", triggerCnt[triggerLevel]);
	//Send external trigger for I-8014W module
	if(triggerSource==2)
	{
		printf("Wait for external trigger signal source to %s .....\n", StateStr[triggerState]);
	}
	else
	{
		printf("Input 0 to start Magic Scan\n");
		scanf("%s",sTemp);
	}
	stopFlag=0;
	pac_i8014W_InstallMagicScanISR(slotIndex,Slot_ISR,triggerLevel);
	pac_i8014W_StartMagicScan(slotIndex);
	T1=GetTickCount();
	for(i=0;i<8;i++)
	totalScaned=0;
	IntCnt=0;
	runFlag=1;
	while (runFlag==1)
	{
		printf("Scanned %ld INT %d \r",totalScaned,IntCnt);
		if(totalScaned>=TargetCnt )
		{
			printf("\n Stop magic scan and FIFO data amount = %d\n", totalScaned);
			runFlag=0;
		}
		Sleep(1);
	}
	pac_i8014W_UnInstallMagicScanISR(slotIndex);
	T2=GetTickCount()-T1; // total time for magic scan to polling data
	printf("Magic scan total spend time = %lu ms  \n\n\n",T2);
	printf("Input 0 to Show AI\n");
	scanf("%s",sTemp);
	ShowAI(slotIndex);
	printf("Input '0' to quit program\n");
	printf("Input 1 to start again\n");
	scanf("%s",sTemp);
	i=atoi(sTemp);
	if ((i==0))
		return 0;
	else
		goto start;
}
void Slot_ISR(int slot)
{
	short ret;
	int i;
	short readCnt=0;
	IntCnt++;
	ret= pac_i8014W_ReadFIFO_InISR(slot,hexData + totalScaned, triggerLevel,&readCnt);
	pac_i8014W_ClearInt(slot);
	if(ret!=0 || readCnt==MAX_FIFO )
	{
		pac_i8014W_StopMagicScan(slot);
		runFlag=0;
		printf("FIFO Error\n");
		return;
	}
	if(readCnt>0)
	{
		totalScaned+= readCnt;
		if(totalScaned >=TargetCnt)
		{
			pac_i8014W_StopMagicScan(slot);
			runFlag=0;
		}
	}
	return;
}
void ShowAI(int slot)
{
	int i;
	float calibratedAI=0;
	printf("Start to printf all data:\n\n\r");
	for(i=0;i<totalScaned;i++)
	{
		if(i%8==7){
			printf("%04X \n",hexData[i]);
		}
		else{
			printf("%04X ",hexData[i]);
		}
		/*if((i%scanChCount)!=0)
		{
			pac_i8014W_CalibrateData(slot, gainArr[i %scanChCount],hexData[i],&calibratedAI);
			printf("Arr[%d][%d]=F[%5.4f]  ",i,i%scanChCount,calibratedAI);
		}
		else
		{
			if (i!=0)
				printf ("\n\r");
			pac_i8014W_CalibrateData(slot, gainArr[i %scanChCount],hexData[i],&calibratedAI);
			printf("Arr[%d][%d]=F[%5.4f]  ",i, i%scanChCount,calibratedAI);
		}*/
	}
	printf("\n---------\n");
}