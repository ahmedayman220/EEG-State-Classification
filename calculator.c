#include <REGX52.H>

// ================= LCD ===================
#define LCD_DATA P0

sbit RS = P2^0;
sbit RW = P2^1;
sbit EN = P2^2;

// ================= KEYPAD ===============
sbit C1 = P3^4;   // pin14
sbit C2 = P3^5;   // pin15
sbit C3 = P3^6;   // pin16
sbit C4 = P3^7;   // pin17

sbit R1 = P3^2;   // pin12
sbit R2 = P3^1;   // pin11
sbit R3 = P3^0;   // pin10
sbit R4 = P3^3;   // pin13

// =============== DELAY ===================
void delay_ms(unsigned int ms)
{
    unsigned int i, j;
    for(i = 0; i < ms; i++)
        for(j = 0; j < 123; j++);
}

// =============== LCD FUNCTIONS ===========
void lcd_pulse(void)
{
    EN = 1;
    delay_ms(2);
    EN = 0;
    delay_ms(2);
}

void lcd_cmd(unsigned char cmd)
{
    RS = 0;
    RW = 0;
    LCD_DATA = cmd;
    lcd_pulse();
}

void lcd_data(unsigned char dat)
{
    RS = 1;
    RW = 0;
    LCD_DATA = dat;
    lcd_pulse();
}

void lcd_clear(void)
{
    lcd_cmd(0x01);
    delay_ms(2);
}

void lcd_goto(unsigned char row, unsigned char col)
{
    unsigned char addr;
    if(row == 0) addr = 0x80 + col;
    else         addr = 0xC0 + col;
    lcd_cmd(addr);
}

void lcd_print(char *str)
{
    while(*str)
        lcd_data(*str++);
}

void lcd_print_num(long n)
{
    char buf[12];
    char i = 0;

    if(n == 0)
    {
        lcd_data('0');
        return;
    }

    if(n < 0)
    {
        lcd_data('-');
        n = -n;
    }

    while(n > 0 && i < 11)
    {
        buf[i++] = (n % 10) + '0';
        n /= 10;
    }

    while(i--)
        lcd_data(buf[i]);
}

void lcd_init(void)
{
    delay_ms(20);
    lcd_cmd(0x38);
    lcd_cmd(0x0C);
    lcd_cmd(0x06);
    lcd_clear();
}

// =============== KEYPAD SCAN =============
char keypad_scan(void)
{
    C1 = C2 = C3 = C4 = 1;

    C1=0; C2=1; C3=1; C4=1;
    if(R1==0) return '7';
    if(R2==0) return '4';
    if(R3==0) return '1';
    if(R4==0) return 'C';

    C1=1; C2=0; C3=1; C4=1;
    if(R1==0) return '8';
    if(R2==0) return '5';
    if(R3==0) return '2';
    if(R4==0) return '0';

    C1=1; C2=1; C3=0; C4=1;
    if(R1==0) return '9';
    if(R2==0) return '6';
    if(R3==0) return '3';
    if(R4==0) return '=';

    C1=1; C2=1; C3=1; C4=0;
    if(R1==0) return '/';
    if(R2==0) return '*';
    if(R3==0) return '-';
    if(R4==0) return '+';

    return 0;
}

char keypad_getkey(void)
{
    char k;
    while(1)
    {
        k = keypad_scan();
        if(k != 0)
        {
            delay_ms(25);
            if(keypad_scan() == k)
            {
                while(keypad_scan() != 0);
                return k;
            }
        }
    }
}

// =============== CALC LOGIC ==============
long calc_apply(long a, long b, char op, unsigned char *err)
{
    *err = 0;

    switch(op)
    {
        case '+': return a + b;
        case '-': return a - b;
        case '*': return a * b;
        case '/':
            if(b == 0) { *err = 1; return 0; }
            return a / b;
        default:  return b;
    }
}

// =============== MAIN ====================
void main(void)
{
    long num1 = 0, num2 = 0, res = 0;
    char op = 0;
    unsigned char have_op = 0;
    unsigned char err = 0;
    char key;

    P0 = 0xFF;
    P3 = 0xFF;

    lcd_init();

    lcd_goto(0,0);
    lcd_print("AT89S52 Calc");
    delay_ms(800);
    lcd_clear();

    lcd_goto(0,0);
    lcd_print("Enter:");
    lcd_goto(1,0);

    while(1)
    {
        key = keypad_getkey();

        if(key == 'C')
        {
            num1 = 0; num2 = 0; res = 0;
            op = 0; have_op = 0; err = 0;

            lcd_clear();
            lcd_goto(0,0);
            lcd_print("Enter:");
            lcd_goto(1,0);
            continue;
        }

        if(key=='+' || key=='-' || key=='*' || key=='/')
        {
            if(!have_op)
            {
                op = key;
                have_op = 1;
                lcd_data(' ');
                lcd_data(op);
                lcd_data(' ');
            }
            continue;
        }

        if(key == '=')
        {
            if(have_op)
            {
                res = calc_apply(num1, num2, op, &err);

                lcd_clear();
                lcd_goto(0,0);
                lcd_print("Result:");
                lcd_goto(1,0);

                if(err)
                    lcd_print("Error: /0");
                else
                    lcd_print_num(res);

                num1 = err ? 0 : res;
                num2 = 0;
                have_op = 0;
                op = 0;
            }
            continue;
        }

        if(key >= '0' && key <= '9')
        {
            lcd_data(key);

            if(!have_op)
                num1 = (num1 * 10) + (key - '0');
            else
                num2 = (num2 * 10) + (key - '0');
        }
    }
}
