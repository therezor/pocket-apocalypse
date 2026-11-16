/* Emacs style mode select   -*- C++ -*-
 *-----------------------------------------------------------------------------
 *
 *
 *  PrBoom: a Doom port merged with LxDoom and LSDLDoom
 *  based on BOOM, a modified and improved DOOM engine
 *  Copyright (C) 1999 by
 *  id Software, Chi Hoang, Lee Killough, Jim Flynn, Rand Phares, Ty Halderman
 *  Copyright (C) 1999-2000 by
 *  Jess Haas, Nicolas Kalkhof, Colin Phipps, Florian Schulze
 *  Copyright 2005, 2006 by
 *  Florian Schulze, Colin Phipps, Neil Stevens, Andrey Budko
 *
 *  This program is free software; you can redistribute it and/or
 *  modify it under the terms of the GNU General Public License
 *  as published by the Free Software Foundation; either version 2
 *  of the License, or (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program; if not, write to the Free Software
 *  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA
 *  02111-1307, USA.
 *
 * DESCRIPTION:
 *  DOOM selection menu, options, episode etc. (aka Big Font menus)
 *  Sliders and icons. Kinda widget stuff.
 *  Setup Menus.
 *  Extended HELP screens.
 *  Dynamic HELP screen.
 *
 *-----------------------------------------------------------------------------*/

#include <stdio.h>
#include <fcntl.h>

#include "doomdef.h"
#include "doomstat.h"
#include "dstrings.h"
#include "d_main.h"
#include "v_video.h"
#include "w_wad.h"
#include "r_main.h"
#include "hu_stuff.h"
#include "g_game.h"
#include "s_sound.h"
#include "sounds.h"
#include "m_menu.h"
#include "m_misc.h"
#include "lprintf.h"
#include "am_map.h"
#include "i_main.h"
#include "i_system.h"
#include "i_video.h"
#include "i_sound.h"

#include "global_data.h"
#include "m_font.h"
#include "hal/hal.h"

//
// Text menus: the classic menu graphics (M_NGAME, M_SKILL, ...) are drawn
// as text in the 8x16 panel font instead (m_font.c); they don't survive
// being shrunk to 240x135. Skill names can come from the mod profile.
//
#ifndef MOD_SKILL_1
#define MOD_SKILL_1 "I'm too young to die"
#define MOD_SKILL_2 "Hey, not too rough"
#define MOD_SKILL_3 "Hurt me plenty"
#define MOD_SKILL_4 "Ultra-Violence"
#define MOD_SKILL_5 "Nightmare!"
#endif

static const struct { const char* lump; const char* text; } menu_labels[] =
{
    {"M_NGAME", "New Game"}, {"M_OPTION", "Options"}, {"M_LOADG", "Load Game"},
    {"M_SAVEG", "Save Game"}, {"M_RDTHIS", "Read This"}, {"M_QUITG", "Quit Game"},
    {"M_JKILL", MOD_SKILL_1}, {"M_ROUGH", MOD_SKILL_2}, {"M_HURT", MOD_SKILL_3},
    {"M_ULTRA", MOD_SKILL_4}, {"M_NMARE", MOD_SKILL_5},
    {"M_EPI1", "Episode 1"}, {"M_EPI2", "Episode 2"}, {"M_EPI3", "Episode 3"},
    {"M_EPI4", "Episode 4"},
    {"M_ENDGAM", "End Game"}, {"M_MESSG", "Messages"}, {"M_ARUN", "Always Run"},
    {"M_DETAIL", "Detail"}, {"M_GAMMA", "Brightness"}, {"M_SVOL", "Sound Volume"},
    {"M_SFXVOL", "Sound FX"}, {"M_MUSVOL", "Music"},
    {"M_CTRLS", "Controls"}, {"M_GYRO", "Gyro Aim"}, {"M_KRESET", "Reset Keys"},
    {"M_GYON", "Gyro Aim"}, {"M_GYTRN", "Turn Speed"}, {"M_GYLOK", "Look Speed"},
    {"M_GYINT", "Invert Turn"}, {"M_GYINL", "Invert Look"}, {"M_GYKEY", "Gyro Key"},
    {"M_GYCAL", "Calibrate"},
};

static const char* M_Label(const char* lump)
{
    for (unsigned int i = 0; i < sizeof(menu_labels)/sizeof(menu_labels[0]); i++)
        if (!strncasecmp(lump, menu_labels[i].lump, 8))
            return menu_labels[i].text;

    return NULL;
}

// Panel position of a menu's items (menu x/y are in 320x200 units). A menu
// longer than the panel scrolls: menu_top is its first row shown.
static int menu_top;

#define MENU_VALUE_X 144    // value column: sliders end inside the panel

static int M_ItemX(const menu_t* m)
{
    return m->x * 240 / 320;
}

static int M_ItemY(const menu_t* m, int i)
{
    return m->y * SCREENHEIGHT / 200 - 2 + (i - menu_top) * MF_LINE_H;
}

static int M_Rows(const menu_t* m)
{
    return (SCREENHEIGHT - (m->y * SCREENHEIGHT / 200 - 2)) / MF_LINE_H;
}

static void M_Scroll(const menu_t* m)
{
    const int rows = M_Rows(m);

    if (m->numitems <= rows)
        menu_top = 0;
    else if (_g->itemOn < menu_top)
        menu_top = _g->itemOn;
    else if (_g->itemOn >= menu_top + rows)
        menu_top = _g->itemOn - rows + 1;
}

static boolean M_RowShown(const menu_t* m, int i)
{
    return i >= menu_top && i < menu_top + M_Rows(m);
}

// Slider: steps positions, value marked.
static void M_DrawSlider(int x, int y, int steps, int value)
{
    const int w = 88, h = 7;

    MF_FillRect(x, y + 3, w, h, MF_BLACK);
    MF_FillRect(x + 1, y + 4, w - 2, h - 2, MF_DARK);

    if (steps > 1)
    {
        int fill = (w - 4) * value / (steps - 1);

        MF_FillRect(x + 2, y + 5, fill, h - 4, MF_RED);
        MF_FillRect(x + 1 + fill, y + 2, 3, h + 2, MF_WHITE);
    }
}

static void (*messageRoutine)(int response);

// we are going to be entering a savegame string

#define SKULLXOFF  -32
#define LINEHEIGHT  16

// graphic name of skulls

static const char skullName[2][9] = {"M_SKULL1","M_SKULL2"};


// end of externs added for setup menus

//
// PROTOTYPES
//
void M_NewGame(int choice);
void M_Episode(int choice);
void M_ChooseSkill(int choice);
void M_LoadGame(int choice);
void M_SaveGame(int choice);
void M_Options(int choice);
void M_EndGame(int choice);


void M_ChangeMessages(int choice);
void M_ChangeAlwaysRun(int choice);
void M_ChangeDetail(int choice);
void M_ChangeGamma(int choice);
void M_SfxVol(int choice);
void M_MusicVol(int choice);
void M_StartGame(int choice);
void M_Sound(int choice);
void M_Controls(int choice);
void M_Gyro(int choice);

void M_LoadSelect(int choice);
void M_SaveSelect(int choice);
void M_ReadSaveStrings(void);
void M_QuickSave(void);
void M_QuickLoad(void);

void M_DrawMainMenu(void);
void M_DrawNewGame(void);
void M_DrawEpisode(void);
void M_DrawOptions(void);
void M_DrawSound(void);
void M_DrawLoad(void);
void M_DrawSave(void);

void M_DrawSaveLoadBorder(int x,int y);
void M_SetupNextMenu(const menu_t *menudef);
void M_DrawThermo(int x,int y,int thermWidth,int thermDot);
void M_WriteText(int x, int y, const char *string);
int  M_StringWidth(const char *string);
int  M_StringHeight(const char *string);
void M_StartMessage(const char *string,void *routine,boolean input);
void M_ClearMenus (void);

// phares 3/30/98
// prototypes added to support Setup Menus and Extended HELP screens

void M_Setup(int choice);


// end of prototypes added to support Setup Menus and Extended HELP screens

/////////////////////////////////////////////////////////////////////////////
//
// DOOM MENUS
//

/////////////////////////////
//
// MAIN MENU
//

// main_e provides numerical values for which Big Font screen you're on

enum
{
  newgame = 0,
  loadgame,
  savegame,
  options,
  main_end
};

//
// MainMenu is the definition of what the main menu Screen should look
// like. Each entry shows that the cursor can land on each item (1), the
// built-in graphic lump (i.e. "M_NGAME") that should be displayed,
// the program which takes over when an item is selected, and the hotkey
// associated with the item.
//

static const menuitem_t MainMenu[]=
{
  {1,"M_NGAME", M_NewGame},
  {1,"M_OPTION",M_Options},
  {1,"M_LOADG", M_LoadGame},
  {1,"M_SAVEG", M_SaveGame},
};

static const menu_t MainDef =
{
  main_end,       // number of menu items
  MainMenu,       // table that defines menu items
  M_DrawMainMenu, // drawing routine
  97,64,          // initial cursor position
  NULL,0,
};

//
// M_DrawMainMenu
//

void M_DrawMainMenu(void)
{
  // a mod's own logo (tools/ui_art.py) is made at panel size
  const int logo = W_CheckNumForName("M_LOGO");

  if (logo >= 0)
  {
    const patch_t* p = W_CacheLumpNum(logo);
    V_DrawPatchNoScale((240 - p->width) / 2, 2, p);
  }
  else
    V_DrawNamePatch(94, 2, 0, "M_DOOM", CR_DEFAULT, VPT_STRETCH);
}

/////////////////////////////
//
// EPISODE SELECT
//

//
// episodes_e provides numbers for the episode menu items. The default is
// 4, to accomodate Ultimate Doom. If the user is running anything else,
// this is accounted for in the code.
//

enum
{
  ep1,
  ep2,
  ep3,
  ep4,
  ep_end
};


// The definitions of the Registered/Shareware Episodes menu

static const menuitem_t EpisodeMenu3[]=
{
  {1,"M_EPI1", M_Episode},
  {1,"M_EPI2", M_Episode},
  {1,"M_EPI3", M_Episode}
};

static const menu_t EpiDef3 =
{
  ep_end-1,        // # of menu items
  EpisodeMenu3,   // menuitem_t ->
  M_DrawEpisode, // drawing routine ->
  48,63,         // x,y
  &MainDef,0,
};

// The definitions of the Episodes menu

static const menuitem_t EpisodeMenu[]=
{
  {1,"M_EPI1", M_Episode},
  {1,"M_EPI2", M_Episode},
  {1,"M_EPI3", M_Episode},
  {1,"M_EPI4", M_Episode}
};

static const menu_t EpiDef =
{
  ep_end,        // # of menu items
  EpisodeMenu,   // menuitem_t ->
  M_DrawEpisode, // drawing routine ->
  48,63,         // x,y
  &MainDef,0,
};

// numerical values for the New Game menu items

enum
{
  killthings,
  toorough,
  hurtme,
  violence,
  nightmare,
  newg_end
};

// The definitions of the New Game menu

static const menuitem_t NewGameMenu[]=
{
  {1,"M_JKILL", M_ChooseSkill},
  {1,"M_ROUGH", M_ChooseSkill},
  {1,"M_HURT",  M_ChooseSkill},
  {1,"M_ULTRA", M_ChooseSkill},
  {1,"M_NMARE", M_ChooseSkill}
};

static const menu_t NewDef =
{
  newg_end,       // # of menu items
  NewGameMenu,    // menuitem_t ->
  M_DrawNewGame,  // drawing routine ->
  48,63,          // x,y
  &MainDef,0,
};

//
//    M_Episode
//

void M_DrawEpisode(void)
{
  MF_DrawTextCentered(8, "Which episode?", MF_RED);
}

void M_Episode(int choice)
{
  if ( (_g->gamemode == shareware) && choice)
  {
    M_StartMessage(SWSTRING,NULL,false); // Ty 03/27/98 - externalized
    _g->itemOn = 0;
    return;
  }

  // Yet another hack...
  if ( (_g->gamemode == registered) && (choice > 2))
    {
    lprintf( LO_WARN,
     "M_Episode: 4th episode requires UltimateDOOM\n");
    choice = 0;
    }

  _g->epi = choice;
  M_SetupNextMenu(&NewDef);
  _g->itemOn = 1; // second skill: easy enough for keyboard play on a small screen
}

//
// M_NewGame
//

void M_DrawNewGame(void)
{
  MF_DarkenRect(0, 0, 240, SCREENHEIGHT);
  MF_DrawTextCentered(6, "NEW GAME", MF_RED);
  MF_DrawTextCentered(22, "Choose skill level", MF_GREY);
}

void M_NewGame(int choice)
{
    if ( _g->gamemode == commercial )
    {
		M_SetupNextMenu(&NewDef);
		_g->itemOn = 1; // second skill: easy enough for keyboard play on a small screen
	}else if( (_g->gamemode == shareware) || (_g->gamemode == registered) )
        M_SetupNextMenu(&EpiDef3);
    else
        M_SetupNextMenu(&EpiDef);
}

// CPhipps - static
static void M_VerifyNightmare(int ch)
{
    if (ch != key_enter)
        return;

    G_DeferedInitNew(nightmare,_g->epi+1,1);
}

void M_ChooseSkill(int choice)
{
    if (choice == nightmare)
    {   // Ty 03/27/98 - externalized
        M_StartMessage(NIGHTMARE,M_VerifyNightmare,true);
		_g->itemOn = 0;
    }
    else
    {
        G_DeferedInitNew(choice,_g->epi+1,1);
		M_ClearMenus ();
    }    
}

/////////////////////////////
//
// LOAD GAME MENU
//

// numerical values for the Load Game slots

enum
{
    load1,
    load2,
    load3,
    load4,
    load5,
    load6,
    load7,
    load8,
    load_end
};

// The definitions of the Load Game screen

static const menuitem_t LoadMenue[]=
{
    {1,"", M_LoadSelect},
    {1,"", M_LoadSelect},
    {1,"", M_LoadSelect},
    {1,"", M_LoadSelect},
    {1,"", M_LoadSelect},
    {1,"", M_LoadSelect},
    {1,"", M_LoadSelect},
    {1,"", M_LoadSelect},
};

static const menu_t LoadDef =
{
  load_end,
  LoadMenue,
  M_DrawLoad,
  64,34, //jff 3/15/98 move menu up
  &MainDef,2,
};

#define LOADGRAPHIC_Y 8

//
// M_LoadGame & Cie.
//

void M_DrawLoad(void)
{
    int i;

    MF_DarkenRect(0, 0, 240, SCREENHEIGHT);
    MF_DrawTextCentered(4, "LOAD GAME", MF_RED);

    for (i = 0 ; i < load_end ; i++)
        MF_DrawText(M_ItemX(&LoadDef), M_ItemY(&LoadDef, i), _g->savegamestrings[i],
                    i == _g->itemOn ? MF_YELLOW : MF_WHITE);
}

//
// Draw border for the savegame description
//

void M_DrawSaveLoadBorder(int x,int y)
{
    int i;

    const patch_t* lpatch = W_CacheLumpName("M_LSLEFT");
    const patch_t* mpatch = W_CacheLumpName("M_LSCNTR");
    const patch_t* rpatch = W_CacheLumpName("M_LSRGHT");

    V_DrawPatchNoScale(x-8, y+7, lpatch);

    for (i = 0 ; i < 12 ; i++)
    {
        V_DrawPatchNoScale(x, y+7, mpatch);
        x += 8;
    }

    V_DrawPatchNoScale(x, y+7, rpatch);
}

//
// User wants to load this game
//

void M_LoadSelect(int choice)
{
  // CPhipps - Modified so savegame filename is worked out only internal
  //  to g_game.c, this only passes the slot.

  G_LoadGame(choice, false); // killough 3/16/98, 5/15/98: add slot, cmd

  M_ClearMenus ();
}

//
// Selected from DOOM menu
//

void M_LoadGame (int choice)
{
  /* killough 5/26/98: exclude during demo recordings
   * cph - unless a new demo */

  M_SetupNextMenu(&LoadDef);
  M_ReadSaveStrings();
}

/////////////////////////////
//
// SAVE GAME MENU
//

// The definitions of the Save Game screen

const static menuitem_t SaveMenu[]=
{
  {1,"", M_SaveSelect},
  {1,"", M_SaveSelect},
  {1,"", M_SaveSelect},
  {1,"", M_SaveSelect},
  {1,"", M_SaveSelect},
  {1,"", M_SaveSelect},
  {1,"", M_SaveSelect}, //jff 3/15/98 extend number of slots
  {1,"", M_SaveSelect},
};

const static menu_t SaveDef =
{
  load_end, // same number of slots as the Load Game screen
  SaveMenu,
  M_DrawSave,
  80,34, //jff 3/15/98 move menu up
  &MainDef,3,
};

//
// M_ReadSaveStrings
//  read the strings from the savegame files
//

void M_ReadSaveStrings(void)
{
  FILE * fd;
  for(int i = 0; i<8; i++) {
    char fname[32];
    sprintf(fname, "/sd/doom/DOOM%d.dsg", i);
    fd = fopen(fname, "r");
    if(!fd) {
      strcpy(_g->savegamestrings[i], "EMPTY");
    } else {
      fread(_g->savegamestrings[i], SAVESTRINGSIZE, 1, fd);
      fclose(fd);
    }
  }
}

//
//  M_SaveGame & Cie.
//
void M_DrawSave(void)
{
    int i;

    MF_DarkenRect(0, 0, 240, SCREENHEIGHT);
    MF_DrawTextCentered(4, "SAVE GAME", MF_RED);

    for (i = 0 ; i < load_end ; i++)
        MF_DrawText(M_ItemX(&SaveDef), M_ItemY(&SaveDef, i), _g->savegamestrings[i],
                    i == _g->itemOn ? MF_YELLOW : MF_WHITE);
}

//
// M_Responder calls this when user is finished
//
char save_descr[10];
static void M_DoSave(int slot)
{

  if(_g->gamemode == commercial)
  {
      strcpy(save_descr, "MAP ");
      itoa(_g->gamemap, &save_descr[4], 10);
  }
  else
  {
      strcpy(save_descr, "ExMy");
      save_descr[1] = '0' + _g->gameepisode;
      save_descr[3] = '0' + _g->gamemap;
  }
  G_SaveGame (slot,save_descr);
  M_ClearMenus ();
}

//
// User wants to save. Start string input for M_Responder
//
void M_SaveSelect(int choice)
{
    _g->saveSlot = choice;

    M_DoSave(_g->saveSlot);
}

//
// Selected from DOOM menu
//
void M_SaveGame (int choice)
{
  // killough 10/6/98: allow savegames during single-player demo playback
  if (!_g->usergame && (!_g->demoplayback))
    {
    M_StartMessage(SAVEDEAD,NULL,false); // Ty 03/27/98 - externalized
    return;
    }

  if (_g->gamestate != GS_LEVEL)
    return;

  M_SetupNextMenu(&SaveDef);
  M_ReadSaveStrings();
}

/////////////////////////////
//
// OPTIONS MENU
//

// numerical values for the Options menu items

enum
{                                                   // phares 3/21/98
  endgame,
  messages,
  alwaysrun,
  detail,
  gamma,
  soundvol,
  controlsmenu,
  gyromenu,
  opt_end
};

// The definitions of the Options menu

static const menuitem_t OptionsMenu[]=
{
  // killough 4/6/98: move setup to be a sub-menu of OPTIONs
  {1,"M_ENDGAM", M_EndGame},
  {1,"M_MESSG",  M_ChangeMessages},
  {1,"M_ARUN",   M_ChangeAlwaysRun},
  {1,"M_DETAIL", M_ChangeDetail},
  {2,"M_GAMMA",   M_ChangeGamma},
  {1,"M_SVOL",   M_Sound},
  {1,"M_CTRLS",  M_Controls},
  {1,"M_GYRO",   M_Gyro},
};

const static menu_t OptionsDef =
{
  opt_end,
  OptionsMenu,
  M_DrawOptions,
  60,37,
  &MainDef,1,
};

//
// M_Options
//
static const char msgNames[2][9]  = {"M_MSGOFF","M_MSGON"};
static const char detailNames[2][9]  = {"M_GDLOW","M_GDHIGH"};


void M_DrawOptions(void)
{
  const int vx = MENU_VALUE_X;

  MF_DarkenRect(0, 0, 240, SCREENHEIGHT);
  MF_DrawTextCentered(6, "OPTIONS", MF_RED);

  MF_DrawText(vx, M_ItemY(&OptionsDef, messages), _g->showMessages ? "On" : "Off", MF_GREY);
  MF_DrawText(vx, M_ItemY(&OptionsDef, alwaysrun), _g->alwaysRun ? "On" : "Off", MF_GREY);
  MF_DrawText(vx, M_ItemY(&OptionsDef, detail), _g->highDetail ? "High" : "Low", MF_GREY);
  M_DrawSlider(vx, M_ItemY(&OptionsDef, gamma), 6, _g->gamma);     // PLAYPAL..PLAYPAL5
}

void M_Options(int choice)
{
  M_SetupNextMenu(&OptionsDef);
}

/////////////////////////////
//
// SOUND VOLUME MENU
//

// numerical values for the Sound Volume menu items
// The 'empty' slots are where the sliding scales appear.

enum
{
  sfx_vol,
  sfx_empty1,
  music_vol,
  sfx_empty2,
  sound_end
};

// The definitions of the Sound Volume menu

static const menuitem_t SoundMenu[]=
{
  {2,"M_SFXVOL",M_SfxVol},
  {-1,"",0},
  {2,"M_MUSVOL",M_MusicVol},
  {-1,"",0}
};

static const menu_t SoundDef =
{
  sound_end,
  SoundMenu,
  M_DrawSound,
  80,64,
  &OptionsDef,4,
};

//
// Change Sfx & Music volumes
//

void M_DrawSound(void)
{
  MF_DarkenRect(0, 0, 240, SCREENHEIGHT);
  MF_DrawTextCentered(6, "SOUND VOLUME", MF_RED);

  M_DrawSlider(M_ItemX(&SoundDef), M_ItemY(&SoundDef, sfx_vol + 1), 16, _g->snd_SfxVolume);
  M_DrawSlider(M_ItemX(&SoundDef), M_ItemY(&SoundDef, music_vol + 1), 16, _g->snd_MusicVolume);
}

void M_Sound(int choice)
{
  M_SetupNextMenu(&SoundDef);
}

void M_SfxVol(int choice)
{
  switch(choice)
    {
    case 0:
      if (_g->snd_SfxVolume)
        _g->snd_SfxVolume--;
      break;
    case 1:
      if (_g->snd_SfxVolume < 15)
        _g->snd_SfxVolume++;
      break;
    }

  G_SaveSettings();

  S_SetSfxVolume(_g->snd_SfxVolume /* *8 */);
}

void M_MusicVol(int choice)
{
  switch(choice)
    {
    case 0:
      if (_g->snd_MusicVolume)
        _g->snd_MusicVolume--;
      break;
    case 1:
      if (_g->snd_MusicVolume < 15)
        _g->snd_MusicVolume++;
      break;
    }

  G_SaveSettings();

  S_SetMusicVolume(_g->snd_MusicVolume /* *8 */);
}

/////////////////////////////
//
// CONTROLS MENU: one row per game action (g_game.c controls[]); Enter,
// then the new key (` cancels). A key already in use swaps over.
//

static int bind_wait = -1;      // control waiting for its new key

// A short note in a menu's title row for a while (message boxes close the
// whole menu).
static const char* menu_note;
static int menu_note_tics;

static void M_Note(const char* note)
{
  menu_note = note;
  menu_note_tics = 2 * TICRATE;
}

static void M_DrawTitle(const char* title)
{
  if (menu_note_tics)
    MF_DrawTextCentered(6, menu_note, MF_YELLOW);
  else
    MF_DrawTextCentered(6, title, MF_RED);
}

void M_BindKey(int choice)
{
  bind_wait = choice;
}

void M_ResetKeys(int choice)
{
  G_ResetControls();
  M_Note("DEFAULT KEYS RESTORED");
}

#define CONTROL_ROW {1, "", M_BindKey}

static const menuitem_t ControlsMenu[NUMCONTROLS + 1] =
{
  CONTROL_ROW, CONTROL_ROW, CONTROL_ROW, CONTROL_ROW, CONTROL_ROW,
  CONTROL_ROW, CONTROL_ROW, CONTROL_ROW, CONTROL_ROW, CONTROL_ROW,
  CONTROL_ROW, CONTROL_ROW, CONTROL_ROW, CONTROL_ROW, CONTROL_ROW,
  CONTROL_ROW, CONTROL_ROW, CONTROL_ROW, CONTROL_ROW, CONTROL_ROW,
  {1, "M_KRESET", M_ResetKeys},
};

void M_DrawControls(void);

static const menu_t ControlsDef =
{
  NUMCONTROLS + 1,
  ControlsMenu,
  M_DrawControls,
  40,37,
  &OptionsDef,controlsmenu,
};

void M_DrawControls(void)
{
  const menu_t* m = &ControlsDef;

  MF_DarkenRect(0, 0, 240, SCREENHEIGHT);
  M_DrawTitle(bind_wait >= 0 ? "PRESS A KEY  (` CANCELS)" : "CONTROLS");

  for (int i = 0; i < numcontrols; i++)
  {
    if (!M_RowShown(m, i))
      continue;

    const int y = M_ItemY(m, i);

    MF_DrawText(M_ItemX(m), y, controls[i].name, i == _g->itemOn ? MF_YELLOW : MF_WHITE);
    if (i == bind_wait)
    {
      if (!_g->whichSkull)
        MF_DrawText(MENU_VALUE_X + 8, y, "???", MF_YELLOW);
    }
    else
      MF_DrawText(MENU_VALUE_X + 8, y, G_KeyName(*controls[i].key), MF_GREY);
  }
}

void M_Controls(int choice)
{
  M_SetupNextMenu(&ControlsDef);
}

/////////////////////////////
//
// GYRO AIM MENU (hal/gyro_e32.cpp does the aiming)
//

enum
{
  gyro_on,
  gyro_turn,
  gyro_look,
  gyro_invturn,
  gyro_invlook,
  gyro_key,
  gyro_calibrate,
  gyro_end
};

static void M_GyroChanged(void)
{
  HAL_GyroSaveConfig();
}

void M_GyroToggle(int choice)
{
  HAL_GyroConfig()->on ^= 1;
  M_GyroChanged();
}

static void M_GyroStep(uint8_t* v, int choice)
{
  if (choice == 0 && *v > 0)
    (*v)--;
  else if (choice == 1 && *v < HAL_GYRO_STEPS)
    (*v)++;
  M_GyroChanged();
}

void M_GyroTurn(int choice)
{
  M_GyroStep(&HAL_GyroConfig()->turn, choice);
}

void M_GyroLook(int choice)
{
  M_GyroStep(&HAL_GyroConfig()->look, choice);
}

void M_GyroInvTurn(int choice)
{
  HAL_GyroConfig()->invert_turn ^= 1;
  M_GyroChanged();
}

void M_GyroInvLook(int choice)
{
  HAL_GyroConfig()->invert_look ^= 1;
  M_GyroChanged();
}

void M_GyroKeyMode(int choice)
{
  HAL_GyroConfig()->hold_aims ^= 1;
  M_GyroChanged();
}

void M_GyroCalibrate(int choice)
{
  if (!HAL_GyroAvailable())
    M_Note("NO GYRO ON THIS CARDPUTER");
  else if (HAL_GyroCalibrate())
    M_Note("GYRO CALIBRATED");
  else
    M_Note("IT MOVED: LAY IT DOWN, RETRY");
}

// toggles take left / right / Enter alike (status 2)
static const menuitem_t GyroMenu[] =
{
  {2,"M_GYON",  M_GyroToggle},
  {2,"M_GYTRN", M_GyroTurn},
  {2,"M_GYLOK", M_GyroLook},
  {2,"M_GYINT", M_GyroInvTurn},
  {2,"M_GYINL", M_GyroInvLook},
  {2,"M_GYKEY", M_GyroKeyMode},
  {1,"M_GYCAL", M_GyroCalibrate},
};

void M_DrawGyro(void);

static const menu_t GyroDef =
{
  gyro_end,
  GyroMenu,
  M_DrawGyro,
  40,37,
  &OptionsDef,gyromenu,
};

void M_DrawGyro(void)
{
  const menu_t* m = &GyroDef;
  const hal_gyro_config_t* g = HAL_GyroConfig();
  const int vx = MENU_VALUE_X;
  char buf[24];

  MF_DarkenRect(0, 0, 240, SCREENHEIGHT);
  M_DrawTitle("GYRO AIM");

  MF_DrawText(vx, M_ItemY(m, gyro_on), !HAL_GyroAvailable() ? "No IMU" : g->on ? "On" : "Off", MF_GREY);
  M_DrawSlider(vx, M_ItemY(m, gyro_turn), HAL_GYRO_STEPS + 1, g->turn);
  M_DrawSlider(vx, M_ItemY(m, gyro_look), HAL_GYRO_STEPS + 1, g->look);
  MF_DrawText(vx, M_ItemY(m, gyro_invturn), g->invert_turn ? "On" : "Off", MF_GREY);
  MF_DrawText(vx, M_ItemY(m, gyro_invlook), g->invert_look ? "On" : "Off", MF_GREY);
  snprintf(buf, sizeof(buf), "%s %s", G_KeyName(key_gyrohold), g->hold_aims ? "aims" : "pauses");
  MF_DrawText(vx, M_ItemY(m, gyro_key), buf, MF_GREY);
}

void M_Gyro(int choice)
{
  M_SetupNextMenu(&GyroDef);
}

/////////////////////////////
//
// M_EndGame
//

static void M_EndGameResponse(int ch)
{
  if (ch != key_enter)
    return;

  // killough 5/26/98: make endgame quit if recording or playing back demo
  if (_g->singledemo)
    G_CheckDemoStatus();

  M_ClearMenus ();
  D_StartTitle ();
}

void M_EndGame(int choice)
{
  M_StartMessage(ENDGAME,M_EndGameResponse,true); // Ty 03/27/98 - externalized
}

/////////////////////////////
//
//    Toggle messages on/off
//

void M_ChangeMessages(int choice)
{
  // warning: unused parameter `int choice'
  choice = 0;
  _g->showMessages = 1 - _g->showMessages;

  if (!_g->showMessages)
    _g->player.message = MSGOFF; // Ty 03/27/98 - externalized
  else
    _g->player.message = MSGON ; // Ty 03/27/98 - externalized

  _g->message_dontfuckwithme = true;

  G_SaveSettings();
}


void M_ChangeAlwaysRun(int choice)
{
    // warning: unused parameter `int choice'
    choice = 0;
    _g->alwaysRun = 1 - _g->alwaysRun;

    if (!_g->alwaysRun)
      _g->player.message = RUNOFF; // Ty 03/27/98 - externalized
    else
      _g->player.message = RUNON ; // Ty 03/27/98 - externalized

    G_SaveSettings();
}

void M_ChangeDetail(int choice)
{
    // warning: unused parameter `int choice'
    choice = 0;
    _g->highDetail = 1 - _g->highDetail;

    if (!_g->highDetail)
      _g->player.message = LOWDETAIL; // Ty 03/27/98 - externalized
    else
      _g->player.message = HIGHDETAIL ; // Ty 03/27/98 - externalized

    G_SaveSettings();
}

void M_ChangeGamma(int choice)
{
	switch(choice)
    {
		case 0:
		  if (_g->gamma)
			_g->gamma--;
		  break;
		case 1:
		  if (_g->gamma < 5)
			_g->gamma++;
		  break;
    }
	V_SetPalLump(_g->gamma);
	V_SetPalette(0);

    G_SaveSettings();
}

//
// End of Original Menus
//
/////////////////////////////////////////////////////////////////////////////

/////////////////////////////
//
// General routines used by the Setup screens.
//

//
// M_InitDefaults()
//
// killough 11/98:
//
// This function converts all setup menu entries consisting of cfg
// variable names, into pointers to the corresponding default[]
// array entry. var.name becomes converted to var.def.
//

static void M_InitDefaults(void)
{

}

//
// End of Setup Screens.
//
/////////////////////////////////////////////////////////////////////////////


/////////////////////////////////////////////////////////////////////////////
//
// M_Responder
//
// Examines incoming keystrokes and button pushes and determines some
// action based on the state of the system.
//

boolean M_Responder (event_t* ev)
{
    int    ch;

    ch = -1; // will be changed to a legit char if we're going to use it here


    // Mouse input processing removed

    // Process keyboard input

    if (ev->type == ev_keydown)
    {
        ch = ev->data1;               // phares 4/11/98:
    }                             // down so you can get at the !,#,


    if (ch == -1)
        return false; // we can't use the event here

    // Controls menu: the next key is the new binding (` cancels)
    if (bind_wait >= 0 && _g->menuactive && !_g->messageToPrint)
    {
        if (ch != key_escape)
            G_BindControl(bind_wait, ch);
        bind_wait = -1;
        S_StartSound(NULL, ch != key_escape ? sfx_pistol : sfx_swtchx);
        return true;
    }

    // Take care of any messages that need input

    if (_g->messageToPrint)
    {
        if (_g->messageNeedsInput == true &&
                !(ch == ' ' || ch == 'n' || ch == 'y' || ch == key_escape || ch == key_fire || ch == key_enter)) // phares
            return false;

        _g->menuactive = _g->messageLastMenuActive;
        _g->messageToPrint = 0;
        if (messageRoutine)
            messageRoutine(ch);

        _g->menuactive = false;
        S_StartSound(NULL,sfx_swtchx);
        return true;
    }

    // Pop-up Main menu?

    if (!_g->menuactive)
    {
        if (ch == key_escape)                                     // phares
        {
            M_StartControlPanel ();
            S_StartSound(NULL,sfx_swtchn);
            return true;
        }
        return false;
    }

    // From here on, these navigation keys are used on the BIG FONT menus
    // like the Main Menu.

    if (ch == key_menu_down)                             // phares 3/7/98
    {
        do
        {
            if (_g->itemOn+1 > _g->currentMenu->numitems-1)
                _g->itemOn = 0;
            else
                _g->itemOn++;
            S_StartSound(NULL,sfx_pstop);
        }
        while(_g->currentMenu->menuitems[_g->itemOn].status==-1);
        return true;
    }

    if (ch == key_menu_up)                               // phares 3/7/98
    {
        do
        {
            if (!_g->itemOn)
                _g->itemOn = _g->currentMenu->numitems-1;
            else
                _g->itemOn--;
            S_StartSound(NULL,sfx_pstop);
        }
        while(_g->currentMenu->menuitems[_g->itemOn].status==-1);
        return true;
    }

    if (ch == key_menu_left)                             // phares 3/7/98
    {
        if (_g->currentMenu->menuitems[_g->itemOn].routine &&
                _g->currentMenu->menuitems[_g->itemOn].status == 2)
        {
            S_StartSound(NULL,sfx_stnmov);
            _g->currentMenu->menuitems[_g->itemOn].routine(0);
        }
        return true;
    }

    if (ch == key_menu_right)                            // phares 3/7/98
    {
        if (_g->currentMenu->menuitems[_g->itemOn].routine &&
                _g->currentMenu->menuitems[_g->itemOn].status == 2)
        {
            S_StartSound(NULL,sfx_stnmov);
            _g->currentMenu->menuitems[_g->itemOn].routine(1);
        }
        return true;
    }

    if (ch == key_menu_enter)                            // phares 3/7/98
    {
        if (_g->currentMenu->menuitems[_g->itemOn].routine &&
                _g->currentMenu->menuitems[_g->itemOn].status)
        {
            if (_g->currentMenu->menuitems[_g->itemOn].status == 2)
            {
                _g->currentMenu->menuitems[_g->itemOn].routine(1);   // right arrow
                S_StartSound(NULL,sfx_stnmov);
            }
            else
            {
                _g->currentMenu->menuitems[_g->itemOn].routine(_g->itemOn);
                S_StartSound(NULL,sfx_pistol);
            }
        }
        //jff 3/24/98 remember last skill selected
        // killough 10/98 moved to skill-specific functions
        return true;
    }

    if (ch == key_menu_escape)                           // phares 3/7/98
    {
        M_ClearMenus ();
        S_StartSound(NULL,sfx_swtchx);
        return true;
    }

	//Allow being able to go back in menus ~Kippykip
	if (ch == key_fire)                           // phares 3/7/98
    {
		//If the prevMenu == NULL (Such as main menu screen), then just get out of the menu altogether
		if(_g->currentMenu->prevMenu == NULL)
		{
			M_ClearMenus();
		}else //Otherwise, change to the parent menu and match the row used to get there.
		{
			short previtemOn = _g->currentMenu->previtemOn; //Temporarily store this so after menu change, we store the last row it was on.
			M_SetupNextMenu(_g->currentMenu->prevMenu);					
			_g->itemOn = previtemOn;
		}
        S_StartSound(NULL,sfx_swtchx);
        return true;		
    }
	
    return false;
}

//
// End of M_Responder
//
/////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////
//
// General Routines
//
// This displays the Main menu and gets the menu screens rolling.
// Plus a variety of routines that control the Big Font menu display.
// Plus some initialization for game-dependant situations.

void M_StartControlPanel (void)
{
  // intro might call this repeatedly

  if (_g->menuactive)
    return;

  //jff 3/24/98 make default skill menu choice follow -skill or defaultskill
  //from command line or config file
  //
  // killough 10/98:
  // Fix to make "always floating" with menu selections, and to always follow
  // defaultskill, instead of -skill.

  _g->menuactive = 1;
  _g->currentMenu = &MainDef;         // JDC
}

//
// M_Drawer
// Called after the view has been rendered,
// but before it has been blitted.
//
// killough 9/29/98: Significantly reformatted source
//

void M_Drawer (void)
{
    // Horiz. & Vertically center string and print it.
    // killough 9/29/98: simplified code, removed 40-character width limit
    if (_g->messageToPrint)
    {
        /* cph - strdup string to writable memory */
        char *ms = Z_Strdup(_g->messageString);
        char *p = ms;

        const int h = M_StringHeight(_g->messageString);
        const int w = M_StringWidth(_g->messageString);
        int y = SCREENHEIGHT/2 - h/2;

        MF_DarkenRect(120 - w/2 - 6, y - 4, w + 12, h + 8);

        while (*p)
        {
            char *string = p, c;
            while ((c = *p) && *p != '\n')
                p++;
            *p = 0;
            M_WriteText(120 - M_StringWidth(string)/2, y, string);
            y += MF_LINE_H;
            if ((*p = c))
                p++;
        }
        Z_Free(ms);
    }
    else
        if (_g->menuactive)
        {
            int x,y,max,i;

            const menu_t* m = _g->currentMenu;

            M_Scroll(m);

            if (_g->currentMenu->routine)
                _g->currentMenu->routine();     // call Draw routine

            // DRAW MENU

            x = M_ItemX(m);
            max = m->numitems;

            // items as text, the selected one highlighted
            for (i=0;i<max;i++)
            {
                const char* name = m->menuitems[i].name;
                const char* label = name[0] ? M_Label(name) : NULL;

                if (!M_RowShown(m, i))
                    continue;

                y = M_ItemY(m, i);

                if (label)
                    MF_DrawText(x, y, label, i == _g->itemOn ? MF_YELLOW : MF_WHITE);
                else if (name[0])
                    V_DrawNamePatch(m->x, m->y + i*LINEHEIGHT, 0, name, CR_DEFAULT, VPT_STRETCH);
            }

            // cursor (blinks like the skull did)
            if (!_g->whichSkull)
                MF_DrawText(x - 12, M_ItemY(m, _g->itemOn), ">", MF_YELLOW);

            // more rows above / below
            if (menu_top > 0)
                MF_DrawText(228, M_ItemY(m, menu_top), "^", MF_GREY);
            if (menu_top + M_Rows(m) < max)
                MF_DrawText(228, M_ItemY(m, menu_top + M_Rows(m) - 1), "v", MF_GREY);
        }
}

//
// M_ClearMenus
//
// Called when leaving the menu screens for the real world

void M_ClearMenus (void)
{
  _g->menuactive = 0;
  _g->itemOn = 0;
  menu_top = 0;
  bind_wait = -1;
}

//
// M_SetupNextMenu
//
void M_SetupNextMenu(const menu_t *menudef)
{
  _g->currentMenu = menudef;
  _g->itemOn = 0;
  menu_top = 0;
}

/////////////////////////////
//
// M_Ticker
//
void M_Ticker (void)
{
  if (menu_note_tics)
    menu_note_tics--;

  if (--_g->skullAnimCounter <= 0)
    {
      _g->whichSkull ^= 1;
      _g->skullAnimCounter = 8;
    }
}

/////////////////////////////
//
// Message Routines
//

void M_StartMessage (const char* string,void* routine,boolean input)
{
  _g->messageLastMenuActive = _g->menuactive;
  _g->messageToPrint = 1;
  _g->messageString = string;
  messageRoutine = routine;
  _g->messageNeedsInput = input;
  _g->menuactive = true;
  return;
}


/////////////////////////////
//
// Thermometer Routines
//

//
// M_DrawThermo draws the thermometer graphic for Mouse Sensitivity,
// Sound Volume, etc.
//
// proff/nicolas 09/20/98 -- changed for hi-res
// CPhipps - patch drawing updated
//
void M_DrawThermo(int x,int y,int thermWidth,int thermDot )
{
    int          xx;
    int           i;
    /*
   * Modification By Barry Mead to allow the Thermometer to have vastly
   * larger ranges. (the thermWidth parameter can now have a value as
   * large as 200.      Modified 1-9-2000  Originally I used it to make
   * the sensitivity range for the mouse better. It could however also
   * be used to improve the dynamic range of music and sound affect
   * volume controls for example.
   */
    int horizScaler; //Used to allow more thermo range for mouse sensitivity.
    thermWidth = (thermWidth > 200) ? 200 : thermWidth; //Clamp to 200 max
    horizScaler = (thermWidth > 23) ? (200 / thermWidth) : 8; //Dynamic range
    xx = x;

    int thermm_lump = W_GetNumForName("M_THERMM");

    V_DrawNamePatch(xx, y, 0, "M_THERML", CR_DEFAULT, VPT_STRETCH);

    xx += 8;
    for (i=0;i<thermWidth;i++)
    {
        V_DrawNumPatch(xx, y, 0, thermm_lump, CR_DEFAULT, VPT_STRETCH);
        xx += horizScaler;
    }

    xx += (8 - horizScaler);  /* make the right end look even */

    V_DrawNamePatch(xx, y, 0, "M_THERMR", CR_DEFAULT, VPT_STRETCH);
    V_DrawNamePatch((x+8)+thermDot*horizScaler,y,0,"M_THERMO",CR_DEFAULT,VPT_STRETCH);
}

/////////////////////////////
//
// String-drawing Routines
//

//
// Find string width from hu_font chars
//

int M_StringWidth(const char* string)
{
  return MF_TextWidth(string);
}

//
//    Find string height from hu_font chars
//

int M_StringHeight(const char* string)
{
  return MF_TextHeight(string);
}

//
//    Write a string using the hu_font
//
void M_WriteText (int x,int y,const char* string)
{
    MF_DrawText(x, y, string, MF_WHITE);
}

/////////////////////////////
//
// Initialization Routines to take care of one-time setup
//

//
// M_Init
//
void M_Init(void)
{
  M_InitDefaults();                // killough 11/98
  _g->currentMenu = &MainDef;
  _g->menuactive = 0;
  _g->whichSkull = 0;
  _g->skullAnimCounter = 10;
  _g->messageToPrint = 0;
  _g->messageString = NULL;
  _g->messageLastMenuActive = _g->menuactive;

  M_ReadSaveStrings();
}

//
// End of General Routines
//
/////////////////////////////////////////////////////////////////////////////
