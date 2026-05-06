// i8014W_Basic_Info_Cplusplus.cpp : Defines the entry point for the console application.
//

#include "stdafx.h"
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "..\Lib\pac_i8014W.h"
#pragma comment(lib,"..\\Lib\\pac_i8014W.lib")
int slotIndex=-1;
char gainStr[5][32]={"+/-10V","+/-5V","+/-2.5V","+/-1.25V","+/-20mA"};
short jumper;
short firmware,isofirm;
int changeTypeCode=0;
int _tmain(int argc, _TCHAR* argv[])
{
	int slot,ch;
	short i,HVal;
	int maxCh=8;
	short hVal=0;
	float fVal=0;
	int loop=0;
	char sTemp[20];
	int iGain=0;
	char libDate[32];
	unsigned short gainValue;
	short offsetValue;
	HANDLE hPort;
	unsigned long T1,T3;
start:
	printf("8014W Demo ReadAIHex/ReadAI \n");
	for(slot=0;slot<8;slot++)
	{
		if(pac_i8014W_Init(slot)==0)
		{
			slotIndex=slot;
			break;
		}
	}
	if(slotIndex==-1)
	{
		printf("There is no i8014 at Backplane\n");
		exit(0);
	}
	else
	{
		printf("There is an i8014 at slot %d\n",slotIndex);
	}
	printf("\n****************************");
	printf("\nThis demo show how to use i8014W_ReadAI to read hex and float format analog input data.");
	firmware = pac_i8014W_GetFirmwareVer_L1(slotIndex);
	printf("\nFPGA Version =: %04X",firmware);
	printf("\nLibrary Version =: %04X",pac_i8014W_GetLibVersion());
	isofirm = pac_i8014W_GetFirmwareVer_L2(slotIndex);
	printf("\nISO Version =: %04X",isofirm);
	pac_i8014W_GetLibDate(libDate);
	printf("\nBuild Date =: %s",libDate);
	printf("\n****************************\n");
	jumper = pac_i8014W_GetSingleEndJumper(slotIndex);
	if(jumper)
	{
		maxCh=16;
		printf("i8014W Input Mode=Single-End\n\r");
	}
	else
	{
		maxCh=8;
		printf("i8014W Input Mode=Differential\n\r");
	}
type:
	changeTypeCode=0;
	for(i=0;i<5;i++)
	{
		printf ("\n\t Select %d :  %s",i,gainStr[i]);
	}
	printf("\n\r");
	printf ("Select Gain (0~4):");
	scanf("%s",sTemp);
	iGain=atoi(sTemp);
	pac_i8014W_ReadGainOffset(slotIndex,iGain,&gainValue, &offsetValue);
	printf("Select Gain[%d]=%s ,the Calibrated Gain= %u, Calibrated Offset= %d\n\n",iGain,	gainStr[iGain],gainValue,offsetValue);
read:
	T1=GetTickCount();
	for (;;)
	{
		T3=GetTickCount();
		if ((T3-T1) >1000) // read frequency every 300 ms
		{
			T1=T3;
			for(i=0;i<maxCh;i++)
			{
				pac_i8014W_ReadAIHex( slotIndex, i, iGain,  & hVal);
				pac_i8014W_ReadAI( slotIndex, i, iGain,  & fVal);
				if(i!=maxCh-1 && i!=7)
				{
					printf("[%02d]=[%04X][%+7.4f]\n",i,hVal & 0xffff,fVal);
				}
				else
				{
					printf("[%02d]=[%04X][%+7.4f]\n",i,hVal & 0xffff, fVal);
				}
			}
			printf("\n-----------------------------------------------------------------------------\n");
			loop++;
			if(loop>3)
			{
				loop=0;
				break;
			}
		}
	}
	printf("Input '0' to quit program\n");
	printf("Input '1' to read AI again\n");
	printf("Input '2' or 'T' to select type code\n");
	printf("Input others to start again\n");
	scanf("%s",sTemp);
	i=atoi(sTemp);
	if ((i==0))
		return 0;
	else if((i==1))
		goto read;
	else if((i==2))
		goto type;
	else
		goto start;
	return 0;
}