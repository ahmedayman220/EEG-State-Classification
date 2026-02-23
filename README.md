#include <REGX52.H>

// ---------------- LCD PINS ----------------
#define LCD_DATA P2

sbit LCD_RS = P3^0;
sbit LCD_RW = P3^1;
sbit LCD_EN = P3^2;

// ---------------- KEYPAD PORT -------------
#define KEYPAD P1

// ----------- simple delay -----------------
void delay_ms(unsigned int ms)
{
    unsigned int i, j;
    for(i = 0; i < ms; i++)
        for(j = 0; j < 123; j++);  // ~1ms at ~11.0592MHz (approx)
}

// --------------- LCD low level ------------
void lcd_pulse_enable(void)
{
    LCD_EN = 1;
    delay_ms(2);
    LCD_EN = 0;
}

void lcd_cmd(unsigned char cmd)
{
    LCD_RS = 0;
    LCD_RW = 0;
    LCD_DATA = cmd;
    lcd_pulse_enable();
    delay_ms(2);
}

void lcd_data(unsigned char dat)
{
    LCD_RS = 1;
    LCD_RW = 0;
    LCD_DATA = dat;
    lcd_pulse_enable();
    delay_ms(2);
}

void lcd_init(void)
{
    delay_ms(20);
    lcd_cmd(0x38); // 8-bit, 2 line, 5x7
    lcd_cmd(0x0C); // display ON, cursor OFF
    lcd_cmd(0x01); // clear
    lcd_cmd(0x06); // entry mode
}

void lcd_goto(unsigned char row, unsigned char col)
{
    unsigned char addr;
    if(row == 0) addr = 0x80 + col;
    else         addr = 0xC0 + col;
    lcd_cmd(addr);
}

void lcd_print(char *s)
{
    while(*s) lcd_data(*s++);
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

// ------------- KEYPAD scan ----------------
// Mapping table
const char keymap[4][4] = {
    {'1','2','3','+'},
    {'4','5','6','-'},
    {'7','8','9','*'},
    {'C','0','=','/'}
};

char keypad_getkey(void)
{
    unsigned char row, col;

    // Rows: P1.0..P1.3, Cols: P1.4..P1.7
    // Set columns as inputs (write 1s), rows will be driven
    KEYPAD |= 0xF0; // P1.4..P1.7 = 1

    while(1)
    {
        for(row = 0; row < 4; row++)
        {
            // Drive one row low, others high
            KEYPAD |= 0x0F;         // all rows high
            KEYPAD &= ~(1 << row);  // current row low

            // Read columns
            if((KEYPAD & 0xF0) != 0xF0)
            {
                delay_ms(20); // debounce
                if((KEYPAD & 0xF0) != 0xF0)
                {
                    // Find which column is low
                    if((KEYPAD & 0x10) == 0) col = 0;
                    else if((KEYPAD & 0x20) == 0) col = 1;
                    else if((KEYPAD & 0x40) == 0) col = 2;
                    else if((KEYPAD & 0x80) == 0) col = 3;
                    else col = 0;

                    // wait for release
                    while((KEYPAD & 0xF0) != 0xF0);

                    return keymap[row][col];
                }
            }
        }
    }
}

// ----------- Calculator logic -------------
long apply_op(long a, long b, char op, bit *err)
{
    *err = 0;
    switch(op)
    {
        case '+': return a + b;
        case '-': return a - b;
        case '*': return a * b;
        case '/':
            if(b == 0) { *err = 1; return 0; }
            return a / b; // integer division
        default:
            return b;
    }
}

void main(void)
{
    long num1 = 0, num2 = 0, result = 0;
    char op = 0;
    char key;
    bit have_op = 0;
    bit err = 0;

    lcd_init();
    lcd_goto(0,0);
    lcd_print("8051 Calculator");
    delay_ms(1000);
    lcd_cmd(0x01);

    lcd_goto(0,0);
    lcd_print("Enter:");

    lcd_goto(1,0);

    while(1)
    {
        key = keypad_getkey();

        // Clear
        if(key == 'C')
        {
            num1 = 0; num2 = 0; result = 0;
            op = 0; have_op = 0; err = 0;
            lcd_cmd(0x01);
            lcd_goto(0,0);
            lcd_print("Enter:");
            lcd_goto(1,0);
            continue;
        }

        // Operator
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
            // If operator pressed again, ignore (simple behavior)
            continue;
        }

        // Evaluate
        if(key == '=')
        {
            if(have_op)
            {
                result = apply_op(num1, num2, op, &err);

                lcd_cmd(0x01);
                lcd_goto(0,0);
                lcd_print("Result:");

                lcd_goto(1,0);
                if(err)
                    lcd_print("Error: /0");
                else
                    lcd_print_num(result);

                // Prepare for next: result becomes num1
                num1 = err ? 0 : result;
                num2 = 0;
                have_op = 0;
                op = 0;
            }
            continue;
        }

        // Digit
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
